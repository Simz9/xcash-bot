
import os
import json
import logging
import sqlite3
import re
from difflib import SequenceMatcher

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# الإعدادات
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "").strip()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_FILE = os.path.join(BASE_DIR, "knowledge_base.json")
DATABASE_FILE = os.path.join(BASE_DIR, "bot_database.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ==============================
# قاعدة البيانات
# ==============================

def get_connection():
    return sqlite3.connect(DATABASE_FILE)


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                support_message_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)


def save_support_message(support_message_id, user_id):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO support_messages
            (support_message_id, user_id)
            VALUES (?, ?)
            """,
            (support_message_id, user_id),
        )


def get_support_user(support_message_id):
    with get_connection() as conn:
        result = conn.execute(
            """
            SELECT user_id FROM support_messages
            WHERE support_message_id = ?
            """,
            (support_message_id,),
        ).fetchone()

    return result[0] if result else None


# ==============================
# تحميل قاعدة المعرفة
# ==============================

def load_knowledge():
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("قاعدة المعرفة يجب أن تكون كائن JSON")

        return data

    except FileNotFoundError:
        logger.error("ملف knowledge_base.json غير موجود")
        return {"categories": []}

    except Exception:
        logger.exception("حدث خطأ أثناء تحميل قاعدة المعرفة")
        return {"categories": []}


KNOWLEDGE = load_knowledge()


# ==============================
# أدوات النصوص والبحث
# ==============================

def normalize_text(text):
    text = text.lower().strip()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def find_answer(user_text):
    normalized_user = normalize_text(user_text)

    if not normalized_user:
        return None

    best_answer = None
    best_score = 0

    categories = KNOWLEDGE.get("categories", [])

    for category in categories:
        questions = category.get("questions", [])

        for item in questions:
            answer = item.get("answer", "")
            phrases = item.get("phrases", [])

            if not answer:
                continue

            search_phrases = [item.get("question", "")]
            search_phrases.extend(phrases)

            for phrase in search_phrases:
                normalized_phrase = normalize_text(phrase)

                if not normalized_phrase:
                    continue

                score = SequenceMatcher(
                    None,
                    normalized_user,
                    normalized_phrase
                ).ratio()

                if normalized_phrase in normalized_user:
                    score = max(score, 0.90)

                if normalized_user in normalized_phrase:
                    score = max(score, 0.85)

                if score > best_score:
                    best_score = score
                    best_answer = answer

    # لا نعرض إجابة إذا كانت المطابقة ضعيفة
    if best_score >= 0.58:
        return best_answer

    return None


# ==============================
# القوائم والأزرار
# ==============================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "الأسئلة الشائعة",
                callback_data="faq"
            )
        ],
        [
            InlineKeyboardButton(
                "مميزات البرنامج",
                callback_data="features"
            ),
            InlineKeyboardButton(
                "التحميل والتفعيل",
                callback_data="activation"
            )
        ],
        [
            InlineKeyboardButton(
                "الشروحات والفيديوهات",
                callback_data="videos"
            )
        ],
        [
            InlineKeyboardButton(
                "مركز الدعم الفني",
                callback_data="support"
            )
        ],
        [
            InlineKeyboardButton(
                "موقع XCash Hygen",
                url="https://xcash-accounting.infinityfreeapp.com/"
            )
        ],
    ])


def categories_keyboard():
    buttons = []

    for index, category in enumerate(
        KNOWLEDGE.get("categories", [])
    ):
        name = category.get("name", f"القسم {index + 1}")

        buttons.append([
            InlineKeyboardButton(
                name,
                callback_data=f"category_{index}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "القائمة الرئيسية",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(buttons)


def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "الأسئلة الشائعة",
                callback_data="faq"
            )
        ],
        [
            InlineKeyboardButton(
                "القائمة الرئيسية",
                callback_data="home"
            )
        ],
    ])


# ==============================
# أوامر البوت
# ==============================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["awaiting_support"] = False

    welcome = (
        "مرحباً بك في خدمة عملاء XCash Hygen.\n\n"
        "أنا المساعد الرسمي للبرنامج، ويمكنني مساعدتك "
        "في معرفة المميزات والتحميل والتفعيل والشروحات.\n\n"
        "اختر القسم الذي تريد المساعدة فيه، أو اكتب سؤالك."
    )

    await update.message.reply_text(
        welcome,
        reply_markup=main_keyboard()
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "استخدم /start لعرض القائمة الرئيسية.\n"
        "استخدم /support للتواصل مع الدعم الفني."
    )


async def support_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await begin_support(update, context)


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["awaiting_support"] = False

    await update.message.reply_text(
        "تم إلغاء وضع الدعم الفني.",
        reply_markup=main_keyboard()
    )


# ==============================
# التعامل مع الأزرار
# ==============================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

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
            categories = KNOWLEDGE.get("categories", [])
            category = categories[index]

            questions = category.get("questions", [])

            if not questions:
                await query.edit_message_text(
                    "لا توجد أسئلة مضافة لهذا القسم حالياً.",
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
                        callback_data=(
                            f"answer_{index}_{question_index}"
                        )
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

            answer = item.get("answer", "لا توجد إجابة متاحة.")

            await query.edit_message_text(
                answer,
                reply_markup=back_keyboard()
            )

        except (ValueError, IndexError, KeyError):
            await query.edit_message_text(
                "تعذر العثور على الإجابة.",
                reply_markup=back_keyboard()
            )

        return

    if data == "features":
        answer = (
            "يعرض XCash Hygen مجموعة من أدوات إدارة النشاط التجاري، "
            "مثل نقاط البيع والفواتير والمخزون والموردين والتقارير "
            "والطباعة والنسخ الاحتياطي.\n\n"
            "يمكنك الاطلاع على التفاصيل من الموقع الرسمي."
        )

        await query.edit_message_text(
            answer,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "عرض تفاصيل البرنامج",
                        url="https://xcash-accounting.infinityfreeapp.com/"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "القائمة الرئيسية",
                        callback_data="home"
                    )
                ],
            ])
        )
        return

    if data == "activation":
        await query.edit_message_text(
            "لتحميل البرنامج أو طلب التفعيل، استخدم الموقع الرسمي. "
            "ستجد هناك خطوات التحميل ونموذج طلب التفعيل.\n\n"
            "لا ترسل بيانات التفعيل أو معلوماتك الشخصية هنا.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "صفحة التحميل",
                        url="https://xcash-accounting.infinityfreeapp.com/download"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "طلب التفعيل",
                        url="https://xcash-accounting.infinityfreeapp.com/activation"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "القائمة الرئيسية",
                        callback_data="home"
                    )
                ],
            ])
        )
        return

    if data == "videos":
        await query.edit_message_text(
            "يمكنك مشاهدة الشروحات والفيديوهات التعليمية "
            "من معرض الشروحات الرسمي.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "مشاهدة الشروحات",
                        url="https://xcash-accounting.infinityfreeapp.com/gallery"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "القائمة الرئيسية",
                        callback_data="home"
                    )
                ],
            ])
        )
        return

    if data == "support":
        context.user_data["awaiting_support"] = True

        await query.edit_message_text(
            "أرسل رسالتك الآن إلى الدعم الفني.\n\n"
            "يمكنك إرسال وصف المشكلة أو صورة لها. "
            "سيتم تحويل رسالتك إلى فريق الدعم.\n\n"
            "للإلغاء أرسل /cancel"
        )
        return


# ==============================
# بدء الدعم البشري
# ==============================

async def begin_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["awaiting_support"] = True

    await update.effective_message.reply_text(
        "أرسل رسالتك أو صورة المشكلة إلى الدعم الفني.\n\n"
        "سيتم تحويلها إلى فريق الدعم.\n"
        "للإلغاء أرسل /cancel"
    )


# ==============================
# معالجة رسائل المستخدمين وردود الدعم
# ==============================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    chat_id = update.effective_chat.id

    if message is None:
        return

    # أولاً: استقبال رد موظف الدعم
    if SUPPORT_CHAT_ID:
        try:
            support_chat_id = int(SUPPORT_CHAT_ID)
        except ValueError:
            support_chat_id = None

        if (
            support_chat_id is not None
            and chat_id == support_chat_id
            and message.reply_to_message
        ):
            original_id = message.reply_to_message.message_id
            user_id = get_support_user(original_id)

            if user_id:
                try:
                    await context.bot.copy_message(
                        chat_id=user_id,
                        from_chat_id=chat_id,
                        message_id=message.message_id
                    )

                    await message.reply_text(
                        "تم إرسال ردك إلى العميل."
                    )

                except Exception:
                    logger.exception("تعذر إرسال رد الدعم للعميل")
                    await message.reply_text(
                        "تعذر إرسال الرد إلى العميل."
                    )

            return

    # ثانياً: معالجة رسائل العملاء
    if message.from_user and message.from_user.is_bot:
        return

    if context.user_data.get("awaiting_support"):
        if not SUPPORT_CHAT_ID:
            await message.reply_text(
                "خدمة التحويل للدعم غير مهيأة حالياً. "
                "يمكنك التواصل عبر البريد:\n"
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
                from_chat_id=chat_id,
                message_id=message.message_id
            )

            save_support_message(
                info_message.message_id,
                user.id
            )

            save_support_message(
                copied_message.message_id,
                user.id
            )

            await message.reply_text(
                "تم إرسال رسالتك إلى فريق الدعم الفني.\n"
                "سيتم الرد عليك في أقرب وقت ممكن.\n\n"
                "مدة الرد المتوقعة: 24 إلى 48 ساعة.",
                reply_markup=main_keyboard()
            )

            context.user_data["awaiting_support"] = False

        except Exception:
            logger.exception("فشل تحويل رسالة الدعم")

            await message.reply_text(
                "تعذر إرسال رسالتك حالياً. "
                "يرجى المحاولة لاحقاً أو التواصل عبر:\n"
                "supportxcash@gmail.com"
            )

        return

    # ثالثاً: البحث عن إجابة في قاعدة المعرفة
    if message.text:
        answer = find_answer(message.text)

        if answer:
            await message.reply_text(
                answer,
                reply_markup=back_keyboard()
            )
        else:
            await message.reply_text(
                "عذراً، لم أتمكن من فهم سؤالك.\n\n"
                "يمكنك اختيار أحد الأقسام من القائمة، "
                "أو التواصل مع الدعم الفني.",
                reply_markup=main_keyboard()
            )

        return

    await message.reply_text(
        "إذا كانت لديك مشكلة فنية، اختر مركز الدعم الفني "
        "لإرسال الرسالة أو الصورة.",
        reply_markup=main_keyboard()
    )


# ==============================
# تشغيل البوت
# ==============================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN غير موجود. أضف توكن البوت في متغيرات البيئة."
        )

    initialize_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            message_handler
        )
    )

    logger.info("XCash Hygen Bot is running...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
