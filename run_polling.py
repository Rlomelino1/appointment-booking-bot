# run_polling.py: local development entry point.
# The bot imported from app.bot already has logging configured and handlers
# registered; this just starts long-polling (no webhook/server needed).
# Run with `python run_polling.py`.

from app.bot import bot

if __name__ == "__main__":
    print("Bot is polling... Press Ctrl+C to stop.")
    bot.infinity_polling()
