# Xcash Hygen Telegram Bot

## Files
- `bot.py`: Telegram bot code.
- `requirements.txt`: Python dependencies.
- `.gitignore`: excludes local secrets and runtime files.

## Required environment variables
- `TELEGRAM_BOT_TOKEN`: token from BotFather. Never commit the real token to GitHub.
- `SUPPORT_CHAT_ID`: numeric Telegram chat ID for the support inbox (a staff account or a group).
- `DATABASE_PATH` (optional): database file path; defaults to `bot_data.sqlite3`.

## Commands
Build/install command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
python bot.py
```

## Configure support
1. Set `SUPPORT_CHAT_ID` to the Telegram user ID or group chat ID where staff should receive customer messages.
2. If using a group, add the bot to the group and ensure it can send messages.
3. Staff must reply directly to the bot's customer notification or copied customer message. The bot copies the staff reply to the customer.
4. Test with a separate Telegram account before public launch.

## Important hosting note
This bot uses long polling. Run only one active instance of it at a time; multiple polling instances using the same token can conflict.
A host's free plan may sleep, restart, or not include always-on background workers. Verify the selected plan's current limits before relying on 24/7 operation.

## Before publishing
Replace the example FAQ text in `FAQ_ANSWERS` inside `bot.py` with verified information about Xcash Hygen. Do not publish invented prices, payment instructions, or product claims.
