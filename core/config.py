# config.py: loads and validates environment variables from a .env file
# (or the real environment) using python-dotenv.
# Fails fast at import time with a clear error if a required variable is missing,
# so misconfiguration is caught at startup rather than mid-request.
# Bot-specific variables are prefixed with the bot's name (APPOINTMENT_*),
# so future bots can add their own without collisions.

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill in the value."
        )
    return value


def _optional_int(name: str):
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(
            f"{name} must be a numeric Telegram user id, got {value!r}."
        )


APPOINTMENT_BOT_TOKEN = _require("APPOINTMENT_BOT_TOKEN")
WEIGHT_BOT_TOKEN = _require("WEIGHT_BOT_TOKEN")
DATABASE_URL = _require("DATABASE_URL")

# Webhook-only settings — not required here so polling-based local dev works
# without them. wsgi.py and scripts/set_webhook.py validate them on startup.
APPOINTMENT_WEBHOOK_SECRET = os.getenv("APPOINTMENT_WEBHOOK_SECRET", "")
WEIGHT_WEBHOOK_SECRET = os.getenv("WEIGHT_WEBHOOK_SECRET", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

# Optional: the single Telegram user id allowed to use admin commands.
# Unset -> admin commands reply "not configured".
ADMIN_USER_ID = _optional_int("ADMIN_USER_ID")
