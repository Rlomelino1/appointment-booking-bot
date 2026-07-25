# Appointment Booking Bot

A Telegram bot that walks users through booking an appointment — pick a service, pick a time, confirm — with race-safe booking guaranteed at the database level.

**Live bot: [t.me/ApBookingBot](https://t.me/ApBookingBot)**

Python 3.12 · Flask · pyTelegramBotAPI · PostgreSQL (Neon) · pytest · Render

## Demo

Every step is driven by tappable reply-keyboard buttons; free text works too.

```
You:  /start
Bot:  Hi! I can book appointments for you.
      [Book an appointment] [My bookings] [Help]

You:  Book an appointment
Bot:  Which service would you like?
      1. Haircut (30 min)
      2. Massage (60 min)

You:  1
Bot:  Pick a time:
      1. Mon 27 Jul, 14:00 (UTC-3)
      2. Tue 28 Jul, 09:00 (UTC-3)

You:  1
Bot:  Here's your booking:
      • Service: Haircut
      • When: Mon 27 Jul, 14:00 (UTC-3)
      • Name: Ana Silva
      [Confirm] [Change slot] [Cancel]

You:  Confirm
Bot:  ✅ Booked! Haircut on Mon 27 Jul, 14:00 (UTC-3) under Ana Silva.
```

`/mybookings` lists confirmed appointments and lets the user cancel one (with
a confirmation step); `/cancel` abandons any flow; unrecognized input always
gets a re-prompt showing the valid options — the bot never crashes on input
and never stays silent.

## Architecture

```
 Telegram servers
        │  HTTPS POST /webhook/<secret>          (or long-polling in dev)
        ▼
 wsgi.py — Flask + gunicorn on Render
        │  core/webhook.py: verifies secret, parses Update, logs it
        ▼
 bots/appointment/handlers.py — thin Telegram glue
        │  (user_id, text, display name) in → Reply out; no business logic
        ▼
 bots/appointment/dialogue.py — conversation state machine
        │  pure logic: no Telegram imports, no SQL
        ▼
 bots/appointment/repository.py — data-access layer, all SQL lives here
        │  transactional writes, parameterized queries
        ▼
 PostgreSQL (Neon)
```

The repo is laid out for multiple bots: everything specific to one bot lives
under `bots/<name>/`, while `core/` holds the genuinely shared infrastructure
(config loading, the database connection helper, the webhook security
pattern). Bot-specific env vars carry the bot's name as a prefix
(`APPOINTMENT_BOT_TOKEN`, `APPOINTMENT_WEBHOOK_SECRET`).

Conversation state lives in a `conversation_state` table (state name + JSONB
context per user), not in process memory — so it survives restarts and doesn't
care which gunicorn worker handles the next message. The full state machine
(states, transitions, edge cases) is specified in
[docs/conversation-flow.md](docs/conversation-flow.md), which was written
before the code and is kept authoritative.

## Key design decisions

**The dialogue logic is pure and dependency-injected.**
`handle_message(user_id, text, repo) -> Reply` touches neither Telegram nor
the database directly: the repository is passed in as a parameter, and the
returned `Reply` is a plain dataclass (text + keyboard rows). That one seam is
why the state machine has 51 unit tests that run in ~0.1 s against an
in-memory fake repository — every transition, fallback, and race scenario is
tested without a database or network. It also means the Telegram layer
(`handlers.py`) stays a ~20-line adapter that is boring by design.

**Double-booking is prevented at the SQL level, not in application code.**
A check-then-insert in Python would race: two users can both see a slot as
free and both book it. Instead, booking claims the slot with
`UPDATE slots SET is_booked = true WHERE id = %s AND is_booked = false
RETURNING id` — an atomic compare-and-set. The loser of the race gets no row
back, the transaction (claim + appointment insert share one) writes nothing,
and the bot apologizes and re-offers the remaining slots. Cancellation is the
mirror image: the status flip and slot release share a transaction, and the
`WHERE status = 'confirmed'` guard makes a double-cancel fail loudly instead
of double-freeing the slot.

**Webhook security via a secret path.**
Anyone can POST to a public URL, and a forged request body looks exactly like
a Telegram update. The webhook is therefore mounted at `/webhook/<secret>`,
where the secret is a random 256-bit string known only to Telegram (via
`setWebhook`) and the server. The comparison uses `hmac.compare_digest` to
avoid timing side-channels; wrong secrets get a 403 and are never parsed.

**Store UTC, display local time.**
All timestamps are stored in UTC (`timestamptz`); conversion to human time
happens only at display, in a single formatting function. Each user can pick
their own display timezone with `/timezone` (presets or any IANA name,
validated with `zoneinfo` and stored in `user_settings`); without a setting,
a `BUSINESS_TIMEZONE` env var (default `America/Sao_Paulo`) applies. Every
rendered time carries its zone — e.g. `Fri 31 Jul, 07:00 (UTC-3)` — and
admin-typed slot times are interpreted as business-timezone local and
converted to UTC before storage, so the database never contains an ambiguous
timestamp. The suffix shows tzdata's letter
abbreviation where one exists (CET, PST); for zones where the IANA database
dropped abbreviations (Brazil's BRT was retired in 2019) it falls back to the
plain UTC offset.

**Polling in dev, webhook in prod.**
Long-polling (`run_polling.py`) needs no public URL, so local development
works behind any firewall with zero setup. Production uses a webhook, which
is push-based and lets one small web service handle traffic without a
permanently open poll loop. Both entry points import the same pre-wired bot
from `bots/appointment/bot.py` (handlers registered exactly once, `threaded=False` so
handler exceptions surface in the request that caused them, with full
tracebacks logged to stdout for Render's log tail). Telegram allows either
mode, never both: `scripts/set_webhook.py --delete` switches back to polling.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # then fill in APPOINTMENT_BOT_TOKEN and DATABASE_URL
python scripts/init_db.py          # applies schema.sql + seed.sql
python run_polling.py
```

## Testing

```powershell
# Unit tests (dialogue state machine — no database or bot token needed)
python -m pytest tests/test_dialogue.py

# Full suite, including repository integration tests against PostgreSQL
$env:TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/booking_test"
python -m pytest
```

Unit tests drive real message scripts through the state machine against
`tests/fake_repository.py` and cover the happy path, `/cancel` in every state,
invalid input in every state (state must not change), and slot-taken races.
Integration tests in `tests/test_repository.py` verify the transactional
booking/cancelling behavior against a real PostgreSQL database; they run only
when `TEST_DATABASE_URL` is set and are skipped otherwise. They drop and
recreate all tables around every test — use a dedicated scratch database.

## Deployment

The repo ships a `render.yaml` blueprint defining a free-plan Python web
service (build: `pip install -r requirements.txt`, start: `gunicorn wsgi:app`,
health check: `GET /health`).

1. In the Render dashboard: **New → Blueprint**, pick this repo, apply.
2. Fill in the prompted env vars (all `sync: false`, never stored in the
   repo): `APPOINTMENT_BOT_TOKEN`, `DATABASE_URL` (any hosted Postgres — this
   deployment uses Neon), `APPOINTMENT_WEBHOOK_SECRET`
   (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), and
   `PUBLIC_URL` (the service's `https://….onrender.com` URL).
3. Initialize the database once, locally, against the production
   `DATABASE_URL`: `python scripts/init_db.py`.
4. After the first deploy, register the webhook once:
   `python scripts/set_webhook.py` (with production `APPOINTMENT_BOT_TOKEN`,
   `PUBLIC_URL`, `APPOINTMENT_WEBHOOK_SECRET` in the environment).
5. Verify: `/health` returns `{"status": "ok"}` and the bot answers on
   Telegram.

Free-plan note: Render spins the service down after ~15 idle minutes; the
first message afterwards is answered with a cold-start delay (Telegram
retries delivery, so nothing is lost). An uptime monitor pinging `/health`
keeps it warm.
