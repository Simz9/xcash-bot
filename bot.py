import logging
import os
import sqlite3
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# Configuration
# =========================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SUPPORT_CHAT_ID_RAW = os.getenv("SUPPORT_CHAT_ID", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_data.sqlite3")

# Edit these answers to match the real Xcash Hygen service.
FAQ_ANSWERS = {
    "about": (
        "Xcash Hygen\n\n"
        "ضع هنا وصفًا رسميًا ودقيقًا للخدمة، وما الذي يقدمه البرنامج."
    ),
    "start": (
        "كيفية البدء\n\n"
        "ضع هنا خطوات الاستخدام الصحيحة، أو اطلب من المستخدم التواصل مع الدعم."
    ),
    "problems": (
        "حل المشكلات\n\n"
        "إذا واجهتك مشكلة، أرسل وصفًا واضحًا لها إلى الدعم، مع صورة للشاشة إن أمكن."
    ),
    "payments": (
        "الاشتراكات والمدفوعات\n\n"
        "ضع هنا معلومات الأسعار وطرق الدفع وسياسة الاسترداد المعتمدة. "
        "لا تضع معلومات غير مؤكدة."
    ),
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
# Reduce noisy HTTP logs while keeping application errors visible.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("xcash_hygen_bot")


def get_support_chat_id():
    if not SUPPORT_CHAT_ID_RAW:
        return None
    try:
        return int(SUPPORT_CHAT_ID_RAW)
    except ValueError as exc:
        raise RuntimeError("SUPPORT_CHAT_ID must be a numeric Telegram chat ID.") from exc


SUPPORT_CHAT_ID = get_support_chat_id()


def init_database():
    """Create a small database mapping support messages to the customer who sent them."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS support_message_map (
                support_message_id INTEGER PRIMARY KEY,
                customer_chat_id INTEGER NOT NULL
            )
            """
        )
        conn.commit()


def save_message_mapping(support_message_id: int, customer_chat_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO support_message_map
            (support_message_id, customer_chat_id)
            VALUES (?, ?)
            """,
            (support_message_id, customer_chat_id),
        )
        conn.commit()


def get_customer_for_support_message(support_message_id: int):
    with sqlite3.connect(DATABASE_PATH) as conn:
        row = conn.execute(
            "SELECT customer_chat_id FROM support_message_map WHERE support_message_id = ?",
            (support_message_id,),
        ).fetchone()
    return row[0] if row else None


def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("الأسئلة الشائعة", callback_data="menu:faq")],
            [InlineKeyboardButton("التواصل مع الدعم", callback_data="menu:support")],
            [InlineKeyboardButton("معلومات البرنامج", callback_data="faq:about")],
        ]
    )


def faq_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("ما هو Xcash Hygen؟", callback_data="faq:about")],
            [InlineKeyboardButton("كيفية البدء", callback_data="faq:start")],
            [InlineKeyboardButton("حل المشكلات", callback_data="faq:problems")],
            [InlineKeyboardButton("الاشتراكات والمدفوعات", callback_data="faq:payments")],
            [InlineKeyboardButton("القائمة الرئيسية", callback_data="menu:home")],
        ]
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "مرحبًا بك في بوت دعم Xcash Hygen.\n"
        "اختر أحد الخيارات من القائمة، أو أرسل رسالتك للتواصل مع الدعم.",
        reply_markup=main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        "استخدم الأزرار للتصفح. للتواصل مع الدعم، اضغط «التواصل مع الدعم» ثم أرسل رسالتك.",
        reply_markup=main_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "menu:home":
        await query.edit_message_text(
            "القائمة الرئيسية — اختر ما تحتاج إليه:",
            reply_markup=main_keyboard(),
        )
    elif data == "menu:faq":
        await query.edit_message_text(
            "الأسئلة الشائعة:\nاختر السؤال الذي تريد معرفة إجابته.",
            reply_markup=faq_keyboard(),
        )
    elif data == "menu:support":
        await query.edit_message_text(
            "للتواصل مع الدعم، أرسل رسالتك التالية هنا في المحادثة. "
            "يمكنك إرسال نص أو صورة أو ملف أو رسالة صوتية."
        )
    elif data.startswith("faq:"):
        key = data.split(":", 1)[1]
        answer = FAQ_ANSWERS.get(key)
        if answer:
            await query.edit_message_text(
                answer,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("الأسئلة الشائعة", callback_data="menu:faq")],
                        [InlineKeyboardButton("التواصل مع الدعم", callback_data="menu:support")],
                        [InlineKeyboardButton("القائمة الرئيسية", callback_data="menu:home")],
                    ]
                ),
            )
        else:
            await query.edit_message_text(
                "لم يتم العثور على الإجابة المطلوبة.",
                reply_markup=main_keyboard(),
            )


async def route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route customer messages to support, and support replies back to customers."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat:
        return

    # Support staff can reply to a copied customer message or its notification.
    if SUPPORT_CHAT_ID is not None and chat.id == SUPPORT_CHAT_ID:
        if not message.reply_to_message:
            await message.reply_text(
                "للرد على العميل، استخدم «الرد» على رسالة العميل المنسوخة "
                "أو على إشعار العميل الذي أرسله البوت."
            )
            return

        customer_chat_id = get_customer_for_support_message(
            message.reply_to_message.message_id
        )
        if customer_chat_id is None:
            await message.reply_text(
                "لم أتمكن من تحديد العميل. ردّ مباشرةً على رسالة العميل التي أرسلها البوت."
            )
            return

        try:
            await context.bot.copy_message(
                chat_id=customer_chat_id,
                from_chat_id=chat.id,
                message_id=message.message_id,
            )
            await message.reply_text("تم إرسال الرد إلى العميل.")
        except TelegramError:
            logger.exception("Could not send support reply to customer %s", customer_chat_id)
            await message.reply_text(
                "تعذر إرسال الرد. قد يكون العميل حظر البوت أو لم يبدأ المحادثة معه."
            )
        return

    # Ignore messages from channels or non-user chats on the customer side.
    if chat.type != "private" or user is None:
        return

    if SUPPORT_CHAT_ID is None:
        await message.reply_text(
            "نظام الدعم غير مفعّل حاليًا. يرجى المحاولة لاحقًا."
        )
        return

    user_name = user.full_name or "غير معروف"
    username = f"@{user.username}" if user.username else "لا يوجد"
    notification_text = (
        "رسالة جديدة من عميل\n"
        f"الاسم: {user_name}\n"
        f"اسم المستخدم: {username}\n"
        f"معرّف العميل: {chat.id}\n\n"
        "للرد، استخدم «الرد» على هذا الإشعار أو على رسالة العميل المنسوخة."
    )

    try:
        notice = await context.bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            text=notification_text,
        )
        save_message_mapping(notice.message_id, chat.id)

        copied = await context.bot.copy_message(
            chat_id=SUPPORT_CHAT_ID,
            from_chat_id=chat.id,
            message_id=message.message_id,
        )
        save_message_mapping(copied.message_id, chat.id)

        await message.reply_text(
            "تم إرسال رسالتك إلى فريق الدعم. سنرد عليك هنا عند توفر الرد."
        )
    except TelegramError:
        logger.exception("Could not route customer message to support")
        await message.reply_text(
            "تعذر إرسال رسالتك إلى الدعم حاليًا. حاول لاحقًا."
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled bot error: %s", context.error, exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN environment variable. "
            "Add it in your hosting platform's environment settings."
        )

    init_database()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, route_message)
    )
    application.add_error_handler(error_handler)

    logger.info("Starting Xcash Hygen Telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
