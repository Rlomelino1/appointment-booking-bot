# handlers.py: thin Telegram glue — no business logic.
# One catch-all text handler feeds every message (commands included) into
# app.dialogue.handle_message and translates the returned Reply into a
# Telegram send: keyboard rows become a ReplyKeyboardMarkup, keyboard=None
# removes any previous keyboard.

import logging

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app import repository
from app.config import ADMIN_USER_ID
from app.dialogue import handle_message

logger = logging.getLogger(__name__)


def _display_name(message: Message) -> str:
    parts = [message.from_user.first_name, message.from_user.last_name]
    return " ".join(p for p in parts if p) or "Guest"


def _to_markup(keyboard):
    if keyboard is None:
        return ReplyKeyboardRemove()
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in keyboard:
        markup.row(*row)
    return markup


def register_handlers(bot: TeleBot) -> None:
    """Attach all message handlers to the given bot instance."""

    @bot.message_handler(content_types=["text"])
    def handle_text(message: Message) -> None:
        user_id = message.from_user.id
        try:
            reply = handle_message(
                user_id,
                message.text,
                repository,
                user_name=_display_name(message),
                admin_user_id=ADMIN_USER_ID,
            )
        except Exception:
            # Never leave the user hanging on an internal error, and never
            # rely on telebot to report it for us.
            logger.exception("Error handling message from user %s", user_id)
            bot.send_message(
                message.chat.id,
                "Sorry, something went wrong on our side. "
                "Please try again, or send /start.",
            )
            return
        bot.send_message(
            message.chat.id, reply.text, reply_markup=_to_markup(reply.keyboard)
        )
