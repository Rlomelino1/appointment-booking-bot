# wsgi.py: production entry point, served by gunicorn (`gunicorn wsgi:app`).
# Telegram POSTs each update to /webhook/<secret>; the secret path segment is
# the only authentication, so requests with a wrong secret get 403 and are
# never fed to the bot. The bot imported from app.bot is threaded=False, so
# each update is fully processed (and any error logged) before the 200 goes
# back — Telegram queues further updates until we respond.

import hmac
import logging

import telebot
from flask import Flask, abort, request

from app.bot import bot
from app.config import WEBHOOK_SECRET

logger = logging.getLogger(__name__)

if not WEBHOOK_SECRET:
    raise RuntimeError(
        "Missing required environment variable: WEBHOOK_SECRET. "
        "The webhook app cannot start without it (any random string works, "
        "e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`)."
    )

app = Flask(__name__)

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


@app.post("/webhook/<secret>")
def webhook(secret: str):
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
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


@app.get("/health")
def health():
    return {"status": "ok"}
