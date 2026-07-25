# wsgi.py: production entry point, served by gunicorn (`gunicorn wsgi:app`).
# One Flask app hosts every bot's webhook; the security/parsing pattern lives
# in core/webhook.py. Telegram POSTs each update to the bot's webhook path;
# the secret path segment is the only authentication, so requests with a
# wrong secret get 403 and are never fed to a bot. The weekly check-in route
# is triggered by an external cron service and protected the same way.

import hmac

from flask import Flask, abort

from bots.appointment.bot import bot as appointment_bot
from bots.weight.bot import bot as weight_bot
from bots.weight.handlers import run_weekly_checkin
from core.config import (
    APPOINTMENT_WEBHOOK_SECRET,
    CRON_SECRET,
    WEIGHT_WEBHOOK_SECRET,
)
from core.webhook import handle_webhook_post

_missing = [
    name for name, value in [
        ("APPOINTMENT_WEBHOOK_SECRET", APPOINTMENT_WEBHOOK_SECRET),
        ("WEIGHT_WEBHOOK_SECRET", WEIGHT_WEBHOOK_SECRET),
        ("CRON_SECRET", CRON_SECRET),
    ] if not value
]
if _missing:
    raise RuntimeError(
        f"Missing required environment variable(s): {', '.join(_missing)}. "
        "The webhook app cannot start without them (any random string works, "
        "e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`)."
    )

app = Flask(__name__)


@app.post("/webhook/<secret>")
def appointment_webhook(secret: str):
    return handle_webhook_post(appointment_bot, APPOINTMENT_WEBHOOK_SECRET, secret)


@app.post("/webhook-weight/<secret>")
def weight_webhook(secret: str):
    return handle_webhook_post(weight_bot, WEIGHT_WEBHOOK_SECRET, secret)


@app.post("/tasks/weekly-checkin/<secret>")
def weekly_checkin(secret: str):
    if not hmac.compare_digest(secret, CRON_SECRET):
        abort(403)
    return {"messaged": run_weekly_checkin(weight_bot)}


@app.get("/health")
def health():
    return {"status": "ok"}
