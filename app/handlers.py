# handlers.py: Telegram message and callback handlers.
# Registers handlers on the shared bot instance (from app.bot) and delegates
# conversation logic to app.dialogue and data access to app.repository.

from telebot import TeleBot
from telebot.types import Message


def register_handlers(bot: TeleBot) -> None:
    """Attach all message handlers to the given bot instance."""

    @bot.message_handler(commands=["start"])
    def handle_start(message: Message) -> None:
        bot.reply_to(message, "Hello! I'm the booking bot 🤖 (under construction)")

    @bot.message_handler(content_types=["text"])
    def handle_echo(message: Message) -> None:
        bot.reply_to(message, f"You said: {message.text}")
