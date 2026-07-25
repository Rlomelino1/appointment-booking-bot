# webhook.py: shared Telegram-webhook security and parsing.
# Every bot's webhook route delegates here: the secret path segment is the
# only authentication (constant-time compared), the body is parsed into a
# telebot Update, and the update is logged and fed to the bot synchronously —
# so processing finishes (or fails loudly) before the HTTP 200 goes back.

import hmac
import logging

import telebot
from flask import abort, request

logger = logging.getLogger(__name__)

# Update fields that identify what kind of update arrived, in telebot's order.
_UPDATE_KINDS = (
    "message", "edited_message", "channel_post", "edited_channel_post",
    "inline_query", "chosen_inline_result", "callback_query",
    "my_chat_member", "chat_member", "chat_join_request",
)


def _describe(update):
    """Return (update type, sender user id or None) for logging."""
    for kind in _UPDATE_KINDS:
        payload = getattr(update, kind, None)
        if payload is not None:
            user = getattr(payload, "from_user", None)
            return kind, user.id if user else None
    return "unknown", None


def handle_webhook_post(bot, expected_secret, secret):
    """Body of a POST /webhook/<secret> route for the given bot."""
    if not hmac.compare_digest(secret, expected_secret):
        abort(403)
    try:
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    except Exception:
        update = None
    if update is None:
        logger.warning("Webhook received a body that is not a Telegram update")
        abort(400)
    kind, user_id = _describe(update)
    logger.info("update %s: type=%s user=%s", update.update_id, kind, user_id)
    bot.process_new_updates([update])
    return "", 200
