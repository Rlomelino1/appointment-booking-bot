# wsgi.py: production entry point, served by gunicorn (`gunicorn wsgi:app`).
# Telegram POSTs each update to /webhook/<secret>; the secret path segment is
# the only authentication, so requests with a wrong secret get 403 and are
# never fed to the bot. Handlers run synchronously before the 200 goes back —
# fine at this scale; Telegram queues further updates until we respond.

import hmac

import telebot
from flask import Flask, abort, request

from app.bot import bot
from app.config import WEBHOOK_SECRET
from app.handlers import register_handlers

if not WEBHOOK_SECRET:
    raise RuntimeError(
        "Missing required environment variable: WEBHOOK_SECRET. "
        "The webhook app cannot start without it (any random string works, "
        "e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`)."
    )

register_handlers(bot)
app = Flask(__name__)


@app.post("/webhook/<secret>")
def webhook(secret: str):
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
        abort(403)
    try:
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    except Exception:
        update = None
    if update is None:
        abort(400)
    bot.process_new_updates([update])
    return "", 200


@app.get("/health")
def health():
    return {"status": "ok"}
