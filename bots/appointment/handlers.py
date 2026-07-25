# handlers.py: thin Telegram glue — no business logic.
# One catch-all text handler feeds every message (commands included) into
# dialogue.handle_message and translates the returned Reply into a
# Telegram send (see core/telegram.py for the keyboard conversion).

import logging

from telebot import TeleBot
from telebot.types import Message

from bots.appointment import repository
from bots.appointment.dialogue import handle_message
from core.config import ADMIN_USER_ID
from core.telegram import display_name, to_markup

logger = logging.getLogger(__name__)


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
                user_name=display_name(message),
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
            message.chat.id, reply.text, reply_markup=to_markup(reply.keyboard)
        )
