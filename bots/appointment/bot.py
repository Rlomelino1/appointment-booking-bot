# bot.py: the appointment bot's composition root — configures logging, creates
# the single shared telebot instance, and registers the message handlers
# exactly once. Both entry points (run_polling.py and wsgi.py) just import
# `bot` from here; neither registers handlers itself, so they can't drift apart.

import logging
import sys

import telebot

from bots.appointment.handlers import register_handlers
from core.config import APPOINTMENT_BOT_TOKEN

# Plain stdout logging: Render's log tail (and any docker logs) captures it.
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


class _LoggingExceptionHandler(telebot.ExceptionHandler):
    """Surface exceptions telebot would otherwise swallow.

    Without this, an exception inside a handler is logged at DEBUG only and,
    in webhook mode, permanently wedges telebot's worker thread.
    """

    def handle(self, exception):
        logger.exception("Unhandled exception while processing update")
        return True  # handled: don't let telebot's internals re-raise


# threaded=False: handlers run synchronously inside process_new_updates, so
# webhook processing finishes (or fails loudly, via the handler above) before
# the HTTP 200 is returned — no fire-and-forget worker threads to lose errors.
bot = telebot.TeleBot(
    APPOINTMENT_BOT_TOKEN,
    threaded=False,
    exception_handler=_LoggingExceptionHandler(),
)
register_handlers(bot)
