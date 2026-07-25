# wsgi.py: production entry point, served by gunicorn (`gunicorn wsgi:app`).
# One Flask app hosts every bot's webhook; the security/parsing pattern lives
# in core/webhook.py. Telegram POSTs each update to /webhook/<secret>; the
# secret path segment is the only authentication, so requests with a wrong
# secret get 403 and are never fed to a bot.

from flask import Flask

from bots.appointment.bot import bot as appointment_bot
from core.config import APPOINTMENT_WEBHOOK_SECRET
from core.webhook import handle_webhook_post

if not APPOINTMENT_WEBHOOK_SECRET:
    raise RuntimeError(
        "Missing required environment variable: APPOINTMENT_WEBHOOK_SECRET. "
        "The webhook app cannot start without it (any random string works, "
        "e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`)."
    )

app = Flask(__name__)


@app.post("/webhook/<secret>")
def appointment_webhook(secret: str):
    return handle_webhook_post(appointment_bot, APPOINTMENT_WEBHOOK_SECRET, secret)


@app.get("/health")
def health():
    return {"status": "ok"}
