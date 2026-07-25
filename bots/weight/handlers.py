# handlers.py: the weight bot's thin Telegram glue — no business logic.
# One catch-all text handler feeds every message into dialogue.handle_message;
# run_weekly_checkin is called by the protected cron route in wsgi.py.

import logging

from telebot import TeleBot
from telebot.types import Message

from bots.weight import dialogue, repository
from core.telegram import to_markup

logger = logging.getLogger(__name__)


def register_handlers(bot: TeleBot) -> None:
    """Attach all message handlers to the given bot instance."""

    @bot.message_handler(content_types=["text"])
    def handle_text(message: Message) -> None:
        user_id = message.from_user.id
        try:
            reply = dialogue.handle_message(user_id, message.text, repository)
        except Exception:
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


def run_weekly_checkin(bot: TeleBot) -> int:
    """Send the Saturday prompt to every active subscriber; return the count.

    A failed send (user blocked the bot, deleted their account) is logged and
    skipped so one bad recipient can't break the whole run.
    """
    sent = 0
    for user_id, reply in dialogue.weekly_checkin(repository):
        try:
            bot.send_message(user_id, reply.text, reply_markup=to_markup(reply.keyboard))
            sent += 1
        except Exception:
            logger.exception("Check-in send failed for user %s", user_id)
    return sent
