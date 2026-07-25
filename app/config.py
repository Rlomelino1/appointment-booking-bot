# config.py: loads and validates environment variables (BOT_TOKEN, DATABASE_URL)
# from a .env file (or the real environment) using python-dotenv.
# Fails fast at import time with a clear error if a required variable is missing,
# so misconfiguration is caught at startup rather than mid-request.

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


BOT_TOKEN = _require("BOT_TOKEN")
DATABASE_URL = _require("DATABASE_URL")

# Webhook-only settings — not required here so polling-based local dev works
# without them. wsgi.py and scripts/set_webhook.py validate them on startup.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
