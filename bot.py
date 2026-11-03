
import os
import json
import logging
import sqlite3
import re
from difflib import SequenceMatcher

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ==================================================
# SETTINGS
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "8037929374").strip()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_FILE = os.path.join(BASE_DIR, "knowledge_base.json")
DATABASE_FILE = os.path.join(BASE_DIR, "bot_database.db")

SITE_URL = "https://xcash-accounting.infinityfreeapp.com/"
DOWNLOAD_URL = SITE_URL + "download"
ACTIVATION_URL = SITE_URL + "activation"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("xcash_bot")


# ==================================================
# DATABASE
# ==================================================

def get_connection():
    conn = sqlite3.connect(DATABASE_FILE, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                support_message_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                blocked INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                user_id INTEGER PRIMARY KEY,
                last_topic TEXT,
                last_question TEXT,
                last_answer TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ترحيل العملاء السابقين الذين تواصلوا مع الدعم
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            SELECT DISTINCT user_id FROM support_messages
        """)

        conn.execute("""
            INSERT OR IGNORE INTO settings
            (setting_key, setting_value)
            VALUES ('maintenance', '0')
        """)


def register_user(user):
    if not user or user.is_bot:
        return

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO users
            (user_id, username, full_name, first_seen, last_seen)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                last_seen=CURRENT_TIMESTAMP
        """, (user.id, user.username, user.full_name))


def get_known_user_ids():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT user_id FROM users WHERE blocked=0"
        ).fetchall()

    return [row[0] for row in rows]


def mark_user_blocked(user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET blocked=1 WHERE user_id=?",
            (user_id,)
        )


def set_maintenance(enabled):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO settings (setting_key, setting_value)
            VALUES ('maintenance', ?)
            ON CONFLICT(setting_key)
            DO UPDATE SET setting_value=excluded.setting_value
        """, ("1" if enabled else "0",))


def is_maintenance_enabled():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT setting_value FROM settings
            WHERE setting_key='maintenance'
        """).fetchone()

    return bool(row and row[0] == "1")


def save_conversation(user_id, topic, question, answer):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO conversations
            (user_id, last_topic, last_question, last_answer)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_topic=excluded.last_topic,
                last_question=excluded.last_question,
                last_answer=excluded.last_answer,
                updated_at=CURRENT_TIMESTAMP
        """, (user_id, topic, question, answer))


def get_conversation(user_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT last_topic, last_question, last_answer
            FROM conversations WHERE user_id=?
        """, (user_id,)).fetchone()

    if not row:
        return None

    return {
        "topic": row[0],
        "question": row[1],
        "answer": row[2],
    }


def save_support_message(message_id, user_id):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO support_messages
            (support_message_id, user_id)
            VALUES (?, ?)
        """, (message_id, user_id))


def get_support_user(message_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT user_id FROM support_messages
            WHERE support_message_id=?
        """, (message_id,)).fetchone()

    return row[0] if row else None


# ==================================================
# KNOWLEDGE BASE
# ==================================================

def load_knowledge():
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Invalid knowledge base")

        if not isinstance(data.get("categories"), list):
            raise ValueError("Missing categories")

        logger.info("Knowledge base loaded successfully")
        return data

    except Exception:
        logger.exception("Failed to load knowledge base")
        return {"categories": []}


KNOWLEDGE = load_knowledge()


# ==================================================
# ARABIC TEXT PROCESSING
# ==================================================

DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED]")


def normalize_text(text):
    text = str(text or "").lower().strip()
    text = DIACRITICS.sub("", text)
    text = text.replace("ـ", "")

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "گ": "ك",
        "ڤ": "ف",
        "پ": "ب",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def token_set(text):
    ignored = {
        "ما", "هل", "كيف", "ماذا", "من", "في", "على",
        "عن", "الى", "اريد", "ابغى", "ابي", "ممكن",
        "لو", "سمحت", "يا", "هو", "هي", "هذا",
        "هذه", "انا", "عندي", "عندك", "ال", "و"
    }

    return {
        word for word in normalize_text(text).split()
        if len(word) > 1 and word not in ignored
    }


def calculate_similarity(user_text, phrase):
    user_norm = normalize_text(user_text)
    phrase_norm = normalize_text(phrase)

    if not user_norm or not phrase_norm:
        return 0

    if user_norm == phrase_norm:
        return 1.0

    if phrase_norm in user_norm:
        return 0.96

    if user_norm in phrase_norm:
        return 0.90

    sequence_score = SequenceMatcher(
        None, user_norm, phrase_norm
    ).ratio()

    user_tokens = token_set(user_norm)
    phrase_tokens = token_set(phrase_norm)

    if user_tokens and phrase_tokens:
        overlap = len(user_tokens & phrase_tokens) / len(
            user_tokens | phrase_tokens
        )
    else:
        overlap = 0

    return max(
        sequence_score * 0.65 + overlap * 0.35,
        overlap * 0.88
    )


def find_best_answer(user_text):
    best_item = None
    best_score = 0

    for category in KNOWLEDGE.get("categories", []):
        category_name = category.get("name", "عام")

        for item in category.get("questions", []):
            answer = item.get("answer", "").strip()

            if not answer:
                continue

            phrases = [item.get("question", "")]
            phrases.extend(item.get("phrases", []))

            for phrase in phrases:
                score = calculate_similarity(user_text, phrase)

                if score > best_score:
                    best_score = score

                    best_item = {
                        "answer": answer,
                        "question": item.get("question", ""),
                        "category": category_name,
                        "score": score,
                    }

    return best_item


# ==================================================
# CUSTOMER INTENT ENGINE
# ==================================================

INTENT_PATTERNS = {
    "purchase": [
        "اريد شراء البرنامج",
        "كيف اشتري",
        "طريقة الشراء",
        "اريد اشتراك",
        "كم سعر البرنامج",
        "السعر",
        "بكم البرنامج",
        "هل يمكن شراء البرنامج",
        "اريد اقتناء البرنامج",
    ],

    "activation": [
        "تفعيل البرنامج",
        "كيف افعل البرنامج",
        "طريقة التفعيل",
        "كود التفعيل",
        "مشكلة التفعيل",
        "لم استطع التفعيل",
        "الترخيص",
        "رخصة البرنامج",
    ],

    "installation": [
        "تثبيت البرنامج",
        "كيف اثبت البرنامج",
        "طريقة التثبيت",
        "مشكلة التثبيت",
        "البرنامج لا يثبت",
        "التنصيب",
        "تحميل البرنامج",
    ],

    "printer": [
        "الطابعة لا تعمل",
        "مشكلة الطابعة",
        "اعدادات الطابعة",
        "ربط الطابعة",
        "الطباعة لا تعمل",
        "طابعة حرارية",
        "طابعة usb",
        "طابعة الشبكة",
        "طابعة 58",
        "طابعة 80",
    ],

    "inventory": [
        "المخزون",
        "ادارة المخزون",
        "الكميات",
        "كمية المنتجات",
        "الجرد",
        "حركة المخزون",
        "نقص المنتجات",
    ],

    "sales": [
        "المبيعات",
        "فاتورة بيع",
        "انشاء فاتورة",
        "الفواتير",
        "نقطة البيع",
        "الكاشير",
        "عملية بيع",
    ],

    "reports": [
        "التقارير",
        "تقرير المبيعات",
        "الارباح",
        "حساب الارباح",
        "تقرير يومي",
        "تقرير شهري",
        "تصدير اكسل",
    ],

    "backup": [
        "النسخ الاحتياطي",
        "نسخة احتياطية",
        "استعادة البيانات",
        "استرجاع البيانات",
        "ضاعت بياناتي",
        "نقل البيانات",
    ],

    "technical_problem": [
        "البرنامج لا يعمل",
        "البرنامج لا يفتح",
        "مشكلة تقنية",
        "يوجد خطا",
        "ظهرت مشكلة",
        "البرنامج معلق",
        "البرنامج بطيء",
        "لا استطيع الدخول",
    ],

    "human_support": [
        "اريد موظف",
        "اريد التحدث مع شخص",
        "الدعم الفني",
        "خدمة العملاء",
        "اريد التواصل معكم",
        "اريد التحدث مع الدعم",
        "موظف الدعم",
    ],
}


INTENT_LABELS = {
    "purchase": "الشراء والأسعار",
    "activation": "التفعيل والترخيص",
    "installation": "التحميل والتثبيت",
    "printer": "الطابعات",
    "inventory": "المخزون والجرد",
    "sales": "المبيعات والفواتير",
    "reports": "التقارير والأرباح",
    "backup": "النسخ الاحتياطي",
    "technical_problem": "مشكلة تقنية",
    "human_support": "التواصل مع الدعم",
}



def detect_customer_intent(text):
    """
    تحديد نية العميل باستخدام كلمات وعبارات واضحة.
    تجنب تصنيف الجمل الإيجابية على أنها مشكلات.
    """

    normalized = normalize_text(text)

    if not normalized:
        return None

    # كلمات تدل على وجود مشكلة
    problem_words = [
        "مشكلة", "مشكلتي", "خطا", "خطأ", "لا يعمل",
        "لا تعمل", "لا يشتغل", "لا تشتغل", "لا يطبع",
        "لا تطبع", "متوقف", "تعطل", "عطل", "فشل",
        "يرفض", "لا يقبل", "لا استطيع", "ما اقدر"
    ]

    # كلمات تدل على حالة طبيعية
    positive_words = [
        "تعمل", "يعمل", "شغالة", "شغال",
        "تشتغل", "يشتغل", "تطبع", "تمام"
    ]

    # لا تعتبر الطابعة مشكلة إذا كانت تعمل بشكل طبيعي
    if "طابع" in normalized:
        has_problem = any(word in normalized for word in problem_words)

        has_setup_request = any(word in normalized for word in [
            "ربط", "اعداد", "اضافة", "توصيل",
            "كيف", "طريقة", "جديدة", "شبكة", "usb"
        ])

        has_positive = any(word in normalized for word in positive_words)

        if has_positive and not has_problem and not has_setup_request:
            return None

        if not has_problem and not has_setup_request:
            return None

    # عبارات طلب الدعم البشري
    human_phrases = [
        "اريد موظف", "اريد شخص", "تواصل مع الدعم",
        "الدعم البشري", "موظف دعم", "اكلم الدعم",
        "التحدث مع شخص", "اريد التواصل معكم"
    ]

    if any(phrase in normalized for phrase in human_phrases):
        intent = "human_support"
        return {
            "intent": intent,
            "label": INTENT_LABELS[intent],
            "confidence": 1.0,
        }

    # ترتيب الأولوية للنيات
    intent_keywords = {
        "activation": [
            "تفعيل", "التفعيل", "كود التفعيل",
            "رمز التفعيل", "الترخيص", "مفتاح التفعيل"
        ],

        "purchase": [
            "شراء", "اشتري", "السعر", "كم سعر",
            "بكم", "الاشتراك", "الدفع", "شراء البرنامج"
        ],

        "installation": [
            "تثبيت", "تنصيب", "تحميل البرنامج",
            "تثبيت البرنامج", "تنصيب البرنامج"
        ],

        "printer": [
            "طابعة", "الطابعة", "طباعة",
            "لا يطبع", "لا تطبع", "ربط الطابعة",
            "اعدادات الطابعة"
        ],

        "inventory": [
            "المخزون", "الجرد", "كميات المنتجات",
            "كمية المنتج", "حركة المخزون"
        ],

        "sales": [
            "فاتورة بيع", "فواتير البيع",
            "المبيعات", "عملية البيع"
        ],

        "reports": [
            "التقارير", "تقرير المبيعات",
            "الارباح", "تقرير الارباح",
            "تصدير اكسل", "excel"
        ],

        "backup": [
            "نسخة احتياطية", "النسخ الاحتياطي",
            "استعادة النسخة", "استرجاع البيانات",
            "نسخ البيانات"
        ],

        "technical_problem": [
            "مشكلة", "خطا", "خطأ", "تعطل",
            "لا يعمل", "لا يفتح", "يتوقف",
            "يعلق", "لا استطيع", "ما اقدر"
        ],
    }

    for intent, keywords in intent_keywords.items():
        for keyword in keywords:
            if keyword in normalized:
                return {
                    "intent": intent,
                    "label": INTENT_LABELS[intent],
                    "confidence": 0.95,
                }

    return None


def get_intent_response(intent):
    """
    إرشاد المحادثة حسب نية العميل.
    لا يقدم معلومات غير مؤكدة.
    """

    responses = {
        "purchase": (
            "أستطيع مساعدتك في معرفة طريقة شراء البرنامج.\n"
            "هل تريد معرفة السعر أولًا أم خطوات الشراء؟"
        ),

        "activation": (
            "سأساعدك في موضوع التفعيل.\n"
            "هل لم تحصل على كود التفعيل، أم حصلت عليه "
            "لكن البرنامج لا يقبله؟"
        ),

        "installation": (
            "سأساعدك في تثبيت البرنامج.\n"
            "هل المشكلة في تحميل ملف البرنامج أم أثناء عملية التثبيت؟"
        ),

        "printer": (
            "سأساعدك في إعداد الطابعة.\n"
            "هل تتصل الطابعة عبر USB أم عبر الشبكة؟"
        ),

        "inventory": (
            "هل تريد معرفة طريقة إدارة المخزون، أم لديك مشكلة "
            "في كميات المنتجات أو عملية الجرد؟"
        ),

        "sales": (
            "هل تحتاج شرح إنشاء فاتورة بيع، أم تواجه مشكلة "
            "أثناء تسجيل عملية البيع؟"
        ),

        "reports": (
            "هل تريد استخراج تقرير المبيعات، أم معرفة الأرباح، "
            "أم تصدير التقارير إلى Excel؟"
        ),

        "backup": (
            "هل تريد إنشاء نسخة احتياطية جديدة، أم استعادة "
            "نسخة سابقة من بياناتك؟"
        ),

        "technical_problem": (
            "سأساعدك في تشخيص المشكلة.\n"
            "ما الذي يحدث بالضبط؟ هل تظهر رسالة خطأ أم أن البرنامج "
            "لا يستجيب؟"
        ),

        "human_support": (
            "يمكنك إرسال رسالتك مباشرة إلى فريق الدعم الفني "
            "من خلال زر مركز الدعم الفني."
        ),
    }

    return responses.get(intent)

# ==================================================
# CONVERSATION ENGINE
# ==================================================

GREETINGS = [
    "السلام عليكم", "سلام عليكم", "السلام",
    "مرحبا", "اهلا", "اهلين", "هلا",
    "صباح الخير", "مساء الخير",
    "hi", "hello", "hey"
]

THANKS = [
    "شكرا", "شكرا لك", "مشكور",
    "يعطيك العافيه", "تسلم", "جزاك الله خير"
]

GOODBYES = [
    "مع السلامه", "الى اللقاء",
    "باي", "في امان الله"
]

HOW_ARE_YOU = [
    "كيف حالك", "شلونك", "كيفك", "عامل ايه"
]

YES_WORDS = [
    "نعم", "اي", "ايوه", "ايوا",
    "تمام", "صحيح", "اكيد"
]

NO_WORDS = [
    "لا", "لا شكرا", "مو", "مش"
]


def conversational_reply(text, previous):
    clean = normalize_text(text)

    if any(clean.startswith(normalize_text(x)) for x in GREETINGS):
        return (
            "أهلًا بك في خدمة عملاء XCash Hygen.\n\n"
            "كيف أستطيع مساعدتك اليوم؟ "
            "يمكنك سؤالي عن البرنامج أو كتابة مشكلتك مباشرة.",
            "تحية"
        )

    if clean in [normalize_text(x) for x in HOW_ARE_YOU]:
        return (
            "أنا جاهز لمساعدتك في كل ما يتعلق ببرنامج XCash Hygen. "
            "ما الذي تريد معرفته؟",
            "محادثة عامة"
        )

    if clean in [normalize_text(x) for x in THANKS]:
        return (
            "على الرحب والسعة. إذا احتجت مساعدة أخرى في XCash Hygen فأنا هنا.",
            "شكر"
        )

    if clean in [normalize_text(x) for x in GOODBYES]:
        return (
            "إلى اللقاء. نتمنى لك تجربة موفقة مع XCash Hygen.",
            "وداع"
        )

    if clean in [normalize_text(x) for x in YES_WORDS]:
        if previous and previous.get("topic"):
            return (
                f"حسنًا، بخصوص موضوع {previous['topic']}، "
                "ما التفاصيل التي تريد معرفتها؟",
                previous["topic"]
            )

        return (
            "حسنًا. ما الذي تريد المساعدة فيه تحديدًا؟",
            "توضيح"
        )

    if clean in [normalize_text(x) for x in NO_WORDS]:
        return (
            "لا مشكلة. هل تريد السؤال عن موضوع آخر؟",
            "تغيير الموضوع"
        )

    if clean in ["طيب", "تمام", "اوكي", "حسنا"]:
        return (
            "تمام. اكتب سؤالك أو أخبرني بما تريد تنفيذه في البرنامج.",
            previous.get("topic", "عام") if previous else "عام"
        )

    return None


def extract_followup_answer(text, previous):
    clean = normalize_text(text)

    if not previous or not previous.get("topic"):
        return None

    followups = [
        "كيف", "كيف يعني", "وضح", "اشرح",
        "ماذا تقصد", "وبعدين", "ثم ماذا"
    ]

    if clean in followups:
        return (
            f"آخر موضوع تحدثنا عنه هو: {previous['topic']}.\n"
            "حدد لي الجزء الذي تريد شرحه وسأساعدك."
        )

    return None


# ==================================================
# KEYBOARDS
# ==================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("الأسئلة الشائعة", callback_data="faq")],
        [
            InlineKeyboardButton("مميزات البرنامج", callback_data="features"),
            InlineKeyboardButton("التحميل والتفعيل", callback_data="activation")
        ],
        [InlineKeyboardButton("الشروحات والفيديوهات", callback_data="videos")],
        [InlineKeyboardButton("مركز الدعم الفني", callback_data="support")],
        [InlineKeyboardButton("موقع XCash Hygen", url=SITE_URL)]
    ])


def categories_keyboard():
    buttons = []

    for index, category in enumerate(KNOWLEDGE.get("categories", [])):
        name = category.get("name", f"القسم {index + 1}")

        buttons.append([
            InlineKeyboardButton(
                name[:60],
                callback_data=f"category_{index}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("القائمة الرئيسية", callback_data="home")
    ])

    return InlineKeyboardMarkup(buttons)


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("الأسئلة الشائعة", callback_data="faq")],
        [InlineKeyboardButton("القائمة الرئيسية", callback_data="home")]
    ])


# ==================================================
# ADMIN SYSTEM
# ==================================================

def is_admin(update):
    user = update.effective_user

    return bool(
        user
        and ADMIN_USER_ID
        and str(user.id) == ADMIN_USER_ID
    )


async def send_broadcast(context, text):
    user_ids = get_known_user_ids()

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                disable_web_page_preview=True
            )
            sent += 1

        except Exception as error:
            failed += 1

            error_text = str(error).lower()

            if (
                "blocked" in error_text
                or "deactivated" in error_text
                or "chat not found" in error_text
            ):
                mark_user_blocked(user_id)

            logger.warning(
                "Broadcast failed for %s: %s",
                user_id,
                error
            )

    return sent, failed, len(user_ids)


async def myid_command(update, context):
    user = update.effective_user

    await update.effective_message.reply_text(
        f"Telegram User ID:\n{user.id}"
    )


async def maintenance_on_command(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للإدارة فقط."
        )
        return

    if is_maintenance_enabled():
        await update.effective_message.reply_text(
            "وضع الصيانة مفعّل بالفعل."
        )
        return

    set_maintenance(True)

    notice = (
        "تنبيه من XCash Hygen\n\n"
        "نعتذر عن الإزعاج.\n"
        "نعمل حاليًا على إجراء صيانة وتحديثات لتحسين خدمة العملاء "
        "وتطوير المساعد.\n\n"
        "الخدمة متوقفة مؤقتًا، وسنبلغكم فور عودتها للعمل.\n"
        "شكرًا لتفهمكم."
    )

    sent, failed, total = await send_broadcast(context, notice)

    await update.effective_message.reply_text(
        "تم تفعيل وضع الصيانة.\n\n"
        f"تم الإرسال: {sent}\n"
        f"فشل الإرسال: {failed}\n"
        f"إجمالي المستخدمين المسجلين: {total}"
    )


async def maintenance_off_command(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للإدارة فقط."
        )
        return

    if not is_maintenance_enabled():
        await update.effective_message.reply_text(
            "وضع الصيانة غير مفعّل."
        )
        return

    set_maintenance(False)

    notice = (
        "XCash Hygen عاد للعمل\n\n"
        "تم الانتهاء من أعمال الصيانة والتحديث.\n"
        "عادت خدمة عملاء XCash Hygen للعمل.\n\n"
        "يمكنك الآن إرسال أسئلتك واستخدام خدمات البوت.\n"
        "شكرًا لانتظاركم."
    )

    sent, failed, total = await send_broadcast(context, notice)

    await update.effective_message.reply_text(
        "تم إيقاف وضع الصيانة.\n\n"
        f"تم الإرسال: {sent}\n"
        f"فشل الإرسال: {failed}\n"
        f"إجمالي المستخدمين المسجلين: {total}"
    )


async def broadcast_command(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للإدارة فقط."
        )
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "اكتب نص الإعلان بعد الأمر.\n\n"
            "مثال:\n"
            "/broadcast يتوفر الآن تحديث جديد للبرنامج."
        )
        return

    sent, failed, total = await send_broadcast(
        context,
        "إعلان من XCash Hygen\n\n" + text
    )

    await update.effective_message.reply_text(
        "انتهى إرسال الإعلان.\n\n"
        f"تم الإرسال: {sent}\n"
        f"فشل الإرسال: {failed}\n"
        f"إجمالي المستخدمين: {total}"
    )


async def stats_command(update, context):
    if not is_admin(update):
        await update.effective_message.reply_text(
            "هذا الأمر مخصص للإدارة فقط."
        )
        return

    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM users WHERE blocked=0"
        ).fetchone()[0]

        blocked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE blocked=1"
        ).fetchone()[0]

    await update.effective_message.reply_text(
        "إحصائيات البوت:\n\n"
        f"المستخدمون المسجلون: {total}\n"
        f"المستخدمون المحظورون أو غير المتاحين: {blocked}\n"
        f"وضع الصيانة: {'مفعّل' if is_maintenance_enabled() else 'متوقف'}"
    )


# ==================================================
# USER COMMANDS
# ==================================================

async def start_command(update, context):
    register_user(update.effective_user)

    if is_maintenance_enabled() and not is_admin(update):
        await update.effective_message.reply_text(
            "نعتذر عن الإزعاج.\n\n"
            "خدمة عملاء XCash Hygen تحت الصيانة حاليًا. "
            "سنبلغك عند عودة الخدمة للعمل."
        )
        return

    context.user_data["awaiting_support"] = False

    await update.effective_message.reply_text(
        "مرحبًا بك في خدمة عملاء XCash Hygen.\n\n"
        "أنا مساعد البرنامج، ويمكنني مساعدتك في معرفة المميزات "
        "والتحميل والتفعيل والاستخدام وحل المشكلات الشائعة.\n\n"
        "اختر القسم الذي تريد المساعدة فيه، أو اكتب سؤالك مباشرة.",
        reply_markup=main_keyboard()
    )


async def help_command(update, context):
    if is_maintenance_enabled() and not is_admin(update):
        await update.effective_message.reply_text(
            "خدمة البوت تحت الصيانة حاليًا."
        )
        return

    await update.effective_message.reply_text(
        "استخدم /start لعرض القائمة الرئيسية.\n"
        "استخدم /support للتواصل مع الدعم الفني."
    )


async def support_command(update, context):
    if is_maintenance_enabled() and not is_admin(update):
        await update.effective_message.reply_text(
            "الدعم عبر البوت متوقف مؤقتًا بسبب الصيانة."
        )
        return

    await begin_support(update, context)


async def cancel_command(update, context):
    context.user_data["awaiting_support"] = False

    await update.effective_message.reply_text(
        "تم إلغاء وضع الدعم الفني.",
        reply_markup=main_keyboard()
    )


async def begin_support(update, context):
    context.user_data["awaiting_support"] = True

    await update.effective_message.reply_text(
        "أرسل رسالتك أو صورة المشكلة إلى الدعم الفني.\n\n"
        "سيتم تحويلها إلى فريق الدعم.\n"
        "للإلغاء أرسل /cancel"
    )


# ==================================================
# BUTTON HANDLER
# ==================================================

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    if is_maintenance_enabled() and not is_admin(update):
        await query.edit_message_text(
            "خدمة البوت تحت الصيانة حاليًا. سنبلغك عند عودتها."
        )
        return

    data = query.data

    if data == "home":
        context.user_data["awaiting_support"] = False

        await query.edit_message_text(
            "القائمة الرئيسية لخدمة عملاء XCash Hygen:",
            reply_markup=main_keyboard()
        )
        return

    if data == "faq":
        await query.edit_message_text(
            "اختر القسم الذي تريد الاطلاع على أسئلته:",
            reply_markup=categories_keyboard()
        )
        return

    if data.startswith("category_"):
        try:
            index = int(data.split("_", 1)[1])
            category = KNOWLEDGE["categories"][index]
            questions = category.get("questions", [])

            if not questions:
                await query.edit_message_text(
                    "لا توجد أسئلة مضافة لهذا القسم حاليًا.",
                    reply_markup=back_keyboard()
                )
                return

            buttons = []

            for question_index, item in enumerate(questions):
                question = item.get(
                    "question",
                    f"السؤال {question_index + 1}"
                )

                buttons.append([
                    InlineKeyboardButton(
                        question[:60],
                        callback_data=f"answer_{index}_{question_index}"
                    )
                ])

            buttons.append([
                InlineKeyboardButton(
                    "رجوع للأقسام",
                    callback_data="faq"
                )
            ])

            await query.edit_message_text(
                category.get("name", "الأسئلة"),
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        except (ValueError, IndexError):
            await query.edit_message_text(
                "تعذر فتح هذا القسم.",
                reply_markup=back_keyboard()
            )

        return

    if data.startswith("answer_"):
        try:
            _, category_index, question_index = data.split("_")

            category = KNOWLEDGE["categories"][int(category_index)]
            item = category["questions"][int(question_index)]

            await query.edit_message_text(
                item.get("answer", "لا توجد إجابة متاحة."),
                reply_markup=back_keyboard()
            )

        except (ValueError, IndexError, KeyError):
            await query.edit_message_text(
                "تعذر العثور على الإجابة.",
                reply_markup=back_keyboard()
            )

        return

    if data == "features":
        await query.edit_message_text(
            "يعرض XCash Hygen أدوات إدارة النشاط التجاري، "
            "مثل نقاط البيع والفواتير والمخزون والموردين والتقارير "
            "والطباعة والنسخ الاحتياطي.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("عرض تفاصيل البرنامج", url=SITE_URL)],
                [InlineKeyboardButton("القائمة الرئيسية", callback_data="home")]
            ])
        )
        return

    if data == "activation":
        await query.edit_message_text(
            "لتحميل البرنامج أو طلب التفعيل، استخدم الموقع الرسمي.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("صفحة التحميل", url=DOWNLOAD_URL)],
                [InlineKeyboardButton("طلب التفعيل", url=ACTIVATION_URL)],
                [InlineKeyboardButton("القائمة الرئيسية", callback_data="home")]
            ])
        )
        return

    if data == "videos":
        await query.edit_message_text(
            "يمكنك مشاهدة الشروحات والفيديوهات التعليمية "
            "من معرض الشروحات الرسمي.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("مشاهدة الشروحات", url=SITE_URL + "gallery")],
                [InlineKeyboardButton("القائمة الرئيسية", callback_data="home")]
            ])
        )
        return

    if data == "support":
        await begin_support(update, context)
        return


# ==================================================
# SUPPORT FORWARDING
# ==================================================

async def forward_support_message(update, context, message):
    if not SUPPORT_CHAT_ID:
        await message.reply_text(
            "خدمة التحويل للدعم غير مهيأة حاليًا.\n"
            "supportxcash@gmail.com"
        )
        return

    try:
        support_chat_id = int(SUPPORT_CHAT_ID)
        user = message.from_user

        user_info = (
            "رسالة دعم فني جديدة\n\n"
            f"الاسم: {user.full_name}\n"
            f"معرف المستخدم: {user.id}\n"
            f"اسم المستخدم: @{user.username or 'غير متوفر'}"
        )

        info_message = await context.bot.send_message(
            chat_id=support_chat_id,
            text=user_info
        )

        copied_message = await context.bot.copy_message(
            chat_id=support_chat_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        save_support_message(info_message.message_id, user.id)
        save_support_message(copied_message.message_id, user.id)

        await message.reply_text(
            "تم إرسال رسالتك إلى فريق الدعم الفني.\n"
            "سيتم الرد عليك في أقرب وقت ممكن.\n\n"
            "مدة الرد المتوقعة: 24 إلى 48 ساعة.",
            reply_markup=main_keyboard()
        )

        context.user_data["awaiting_support"] = False

    except Exception:
        logger.exception("Support forwarding failed")

        await message.reply_text(
            "تعذر إرسال رسالتك حاليًا. "
            "يرجى المحاولة لاحقًا أو التواصل عبر:\n"
            "supportxcash@gmail.com"
        )



# ==================================================
# MESSAGE HANDLER
# ==================================================

async def message_handler(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None:
        return

    # ردود موظفي الدعم
    if SUPPORT_CHAT_ID:
        try:
            support_chat_id = int(SUPPORT_CHAT_ID)
        except ValueError:
            support_chat_id = None

        if support_chat_id is not None and chat.id == support_chat_id:
            if message.reply_to_message:
                user_id = get_support_user(
                    message.reply_to_message.message_id
                )

                if user_id:
                    try:
                        await context.bot.copy_message(
                            chat_id=user_id,
                            from_chat_id=chat.id,
                            message_id=message.message_id
                        )

                        await message.reply_text(
                            "تم إرسال ردك إلى العميل."
                        )

                    except Exception:
                        logger.exception("Failed to send support reply")

                        await message.reply_text(
                            "تعذر إرسال الرد إلى العميل."
                        )

            return

    if user and user.is_bot:
        return

    if chat.type == "private" and user:
        register_user(user)

    # الصيانة
    if is_maintenance_enabled() and not is_admin(update):
        await message.reply_text(
            "نعتذر عن الإزعاج.\n\n"
            "خدمة عملاء XCash Hygen تحت الصيانة حاليًا. "
            "سنرسل لك إشعارًا عند عودة الخدمة."
        )
        return

    # وضع الدعم
    if context.user_data.get("awaiting_support"):
        await forward_support_message(update, context, message)
        return

    if message.text:
        text = message.text.strip()
        previous = get_conversation(user.id) if user else None

        # 1. المحادثة الاجتماعية
        social = conversational_reply(text, previous)

        if social:
            answer, topic = social

            if user:
                save_conversation(user.id, topic, text, answer)

            await message.reply_text(
                answer,
                reply_markup=main_keyboard()
            )
            return

        # 2. فهم الأسئلة المتتابعة
        followup = extract_followup_answer(text, previous)

        if followup:
            await message.reply_text(
                followup,
                reply_markup=main_keyboard()
            )
            return

        # 3. اكتشاف نية العميل قبل البحث العام
        detected = detect_customer_intent(text)

        if detected:
            intent = detected["intent"]

            # طلب التواصل مع موظف
            if intent == "human_support":
                await begin_support(update, context)
                return

            intent_answer = get_intent_response(intent)

            if intent_answer:
                if user:
                    save_conversation(
                        user.id,
                        detected["label"],
                        text,
                        intent_answer
                    )

                await message.reply_text(
                    intent_answer,
                    reply_markup=main_keyboard()
                )
                return

        # 4. البحث في قاعدة المعرفة عند عدم اكتشاف نية واضحة
        match = find_best_answer(text)

        if match and match["score"] >= 0.43:
            answer = match["answer"]

            if user:
                save_conversation(
                    user.id,
                    match["category"],
                    text,
                    answer
                )

            await message.reply_text(
                answer,
                reply_markup=back_keyboard()
            )
            return

        # 5. إذا لم نفهم السؤال
        await message.reply_text(
            "لم أتمكن من فهم طلبك بدقة.\n\n"
            "هل يمكنك توضيح ما الذي تريد فعله في XCash Hygen؟\n\n"
            "يمكنك أيضًا اختيار أحد الأقسام أو التواصل مع الدعم الفني.",
            reply_markup=main_keyboard()
        )
        return

    # الصور والملفات والفيديوهات
    if message.photo or message.document or message.video:
        await message.reply_text(
            "وصلتني رسالتك، لكن إذا كانت الصورة أو الملف متعلقًا "
            "بمشكلة في البرنامج، اختر مركز الدعم الفني لإرساله "
            "إلى فريق الدعم.",
            reply_markup=main_keyboard()
        )
        return

    await message.reply_text(
        "يمكنك كتابة سؤالك نصيًا أو اختيار أحد أقسام المساعدة.",
        reply_markup=main_keyboard()
    )

# ==================================================
# MAIN
# ==================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN غير موجود في متغيرات البيئة."
        )

    initialize_database()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # أوامر الإدارة
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("maintenance_on", maintenance_on_command))
    application.add_handler(CommandHandler("maintenance_off", maintenance_off_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("stats", stats_command))

    application.add_handler(CallbackQueryHandler(button_handler))

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_handler
        )
    )

    logger.info("XCash Hygen Bot is running.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
