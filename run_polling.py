# run_polling.py: local development entry point.
# Wires the handlers onto the shared bot instance and starts long-polling
# (no webhook/server needed). Run with `python run_polling.py`.

from app.bot import bot
from app.handlers import register_handlers

if __name__ == "__main__":
    register_handlers(bot)
    print("Bot is polling... Press Ctrl+C to stop.")
    bot.infinity_polling()
