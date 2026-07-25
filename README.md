# Appointment Booking Bot

A Telegram bot for booking appointments, built with pyTelegramBotAPI and backed by PostgreSQL. Users interact with the bot through a guided conversation to pick a service, choose an available date and time, and confirm their booking. It runs in long-polling mode for local development (`run_polling.py`) and as a Flask webhook app served by gunicorn in production (`wsgi.py`).

## Setup

```powershell
# Create and activate a virtual environment (Windows PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1

# macOS / Linux
# python3 -m venv venv
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
copy .env.example .env   # then edit .env and fill in BOT_TOKEN and DATABASE_URL
```

The `venv/` directory is git-ignored — do not commit it.

## Local dev vs production

Locally the bot runs in **polling** mode (`python run_polling.py`): it repeatedly asks Telegram for new updates, which needs no public URL and works from behind any firewall. In production it runs in **webhook** mode: Telegram pushes each update to `POST {PUBLIC_URL}/webhook/{WEBHOOK_SECRET}`, served by `gunicorn wsgi:app` — set `WEBHOOK_SECRET` and `PUBLIC_URL`, then register the URL once with `python scripts/set_webhook.py`. Telegram allows either a webhook or polling, never both, so run `python scripts/set_webhook.py --delete` before switching back to local polling. `GET /health` returns `{"status": "ok"}` for Render health checks and uptime monitors.

## Running tests

```powershell
# Unit tests (dialogue state machine — no database or bot token needed)
python -m pytest tests/test_dialogue.py

# Full suite, including repository integration tests against PostgreSQL
$env:TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/booking_test"
python -m pytest
```

The repository tests in `tests/test_repository.py` run only when
`TEST_DATABASE_URL` is set and are skipped (with a message) otherwise.
They drop and recreate all tables around every test — point the variable at a
dedicated scratch database, never at your real one.
