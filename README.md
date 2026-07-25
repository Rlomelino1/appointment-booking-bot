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

## Deployment (Render)

The repo ships a `render.yaml` blueprint defining a free-plan Python web service
(build: `pip install -r requirements.txt`, start: `gunicorn wsgi:app`, health
check: `/health`).

1. Push the repo to GitHub.
2. In the Render dashboard: **New → Blueprint**, pick this repo, and apply.
   Render creates the `appointment-booking-bot` web service from `render.yaml`.
3. When prompted (the four env vars are `sync: false`, i.e. never stored in the
   repo), fill in:
   - `BOT_TOKEN` — from @BotFather
   - `DATABASE_URL` — a PostgreSQL connection string (e.g. a Render PostgreSQL
     instance's *external* URL, or any other hosted Postgres)
   - `WEBHOOK_SECRET` — generate with
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `PUBLIC_URL` — the service's URL, e.g. `https://appointment-booking-bot.onrender.com`
     (shown at the top of the service page once created)
4. Initialize the database schema and seed data (run locally, pointing at the
   production database): set `DATABASE_URL` in your shell or `.env`, then
   `python scripts/init_db.py`.
5. After the first successful deploy, register the webhook — run locally with
   the production `BOT_TOKEN`, `PUBLIC_URL`, and `WEBHOOK_SECRET` in your
   environment: `python scripts/set_webhook.py`. This is a one-time step;
   redeploys keep the same URL.
6. Verify: `https://<your-service>.onrender.com/health` returns
   `{"status": "ok"}`, and messaging the bot on Telegram gets a reply.

**Free-plan note:** Render free services spin down after ~15 minutes without
traffic, so the first message after an idle period is answered with a delay
while the service wakes up (Telegram retries delivery, so nothing is lost).
Pointing an uptime monitor (e.g. UptimeRobot) at `/health` every 5 minutes
keeps it awake.

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
