import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ضع توكن البوت الذي حصلت عليه من BotFather بين علامتي التنصيص أدناه
TOKEN = os.environ.get("BOT_TOKEN")


# أوقات عمل فريق الدعم
SUPPORT_HOURS = "من الساعة 9 صباحاً وحتى 5 مساءً (بتوقيت المحلي)"

# قائمة البدء والأزرار التفاعلية
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("❓ الأسئلة الشائعة عن Xcash Hygen", callback_data="faq")],
        [InlineKeyboardButton("🛠️ مشاكل شائعة وحلولها", callback_data="troubleshoot")],
        [InlineKeyboardButton("💬 التحدث مع الدعم الفني", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "أهلاً بك في خدمة دعم **Xcash Hygen** 🤖\n\n"
        "كيف يمكنني مساعدتك اليوم؟ يرجى اختيار أحد الخيارات أدناه أو كتابة استفسارك مباشرة:"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# التعامل مع الضغط على الأزرار
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "faq":
        text = "💡 **الأسئلة الشائعة:**\n- ما هو برنامج Xcash Hygen؟\n- كيف يتم ربطه بالنظام؟\n\nيمكنك كتابة سؤالك وسيقوم النظام بالإجابة عليك فوراً."
    elif query.data == "troubleshoot":
        text = "⚠️ **حل المشاكل التقنية:**\nإذا واجهتك مشكلة في التثبيت أو الاتصال، يرجى كتابة وصف المشكلة وسنساعدك."
    elif query.data == "support":
        text = (
            f"✍️ **فريق الدعم الفني:**\n"
            f"يرجى كتابة رسالتك أو استفسارك الآن هنا في المحادثة.\n"
            f"🕒 أوقات عمل الفريق: {SUPPORT_HOURS}.\n"
            "سيتم الرد عليك في أقرب وقت ممكن خلال ساعات العمل."
        )
        context.user_data['waiting_for_support'] = True

    keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['waiting_for_support'] = False
    
    keyboard = [
        [InlineKeyboardButton("❓ الأسئلة الشائعة عن Xcash Hygen", callback_data="faq")],
        [InlineKeyboardButton("🛠️ مشاكل شائعة وحلولها", callback_data="troubleshoot")],
        [InlineKeyboardButton("💬 التحدث مع الدعم الفني", callback_data="support")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("القائمة الرئيسية:", reply_markup=reply_markup)

# الرد على الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    
    if context.user_data.get('waiting_for_support', False):
        await update.message.reply_text(
            f"✅ تم استلام رسالتك بنجاح!\n"
            f"سيتواصل معك أحد أعضاء فريق الدعم خلال فترة العمل ({SUPPORT_HOURS}). شكراً لتواصلك معنا."
        )
        context.user_data['waiting_for_support'] = False
        return

    smart_reply = (
        f"🤖 بناءً على استفسارك حول ( {user_message} ) في نظام Xcash Hygen:\n\n"
        "لقد قمنا بالبحث في قاعدة المعرفة، والإجابة هي:\n"
        "يرجى التأكد من إعدادات الاتصال وقاعدة البيانات الخاصة بالبرنامج.\n\n"
        "إذا لم تكن هذه الإجابة كافية، اضغط على زر الدعم الفني أدناه."
    )
    
    keyboard = [[InlineKeyboardButton("💬 تحويل للدعم البشري", callback_data="support")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(smart_reply, reply_markup=reply_markup)

def main():
    # استبدل YOUR_BOT_TOKEN_HERE بالتوكن الخاص بك هنا أيضاً إذا لزم الأمر
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(faq|troubleshoot|support)$"))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^main_menu$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("البوت يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
