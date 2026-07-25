# bot.py: the weight bot's composition root — configures logging, creates its
# telebot instance, and registers the message handlers exactly once.
# Same shape as bots/appointment/bot.py; see that file for the reasoning
# behind threaded=False and the logging exception handler.

import logging
import sys

import telebot

from bots.weight.handlers import register_handlers
from core.config import WEIGHT_BOT_TOKEN

# Plain stdout logging; basicConfig is a no-op if another bot configured it.
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


class _LoggingExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.exception("Unhandled exception while processing update")
        return True


bot = telebot.TeleBot(
    WEIGHT_BOT_TOKEN,
    threaded=False,
    exception_handler=_LoggingExceptionHandler(),
)
register_handlers(bot)
