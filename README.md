# Telegram Bots

A small collection of Telegram bots sharing one codebase, one PostgreSQL
database, and one deployment. Each bot lives in its own package under
`bots/`; genuinely shared infrastructure (config, database access, webhook
security) lives in `core/`; a single Flask app serves every bot's webhook
from one free Render service.

Python 3.12 · Flask · pyTelegramBotAPI · PostgreSQL (Neon) · pytest · Render

## The bots

### Appointment Booking — [t.me/ApBookingBot](https://t.me/ApBookingBot)

Walks users through booking an appointment — pick a service, pick a time,
confirm — with race-safe booking guaranteed at the database level. Every step
is driven by tappable reply-keyboard buttons; free text works too.

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

`/mybookings` lists confirmed appointments and lets the user cancel one;
`/timezone` sets a per-user display timezone; `/cancel` abandons any flow;
unrecognized input always gets a re-prompt showing the valid options. Admin
commands (`/addslot`, `/slots`, `/appointments`) are restricted to a single
configured user id — for anyone else they fall through to the normal
fallback, so their existence is never revealed. The full state machine
(states, transitions, edge cases) is specified in
[docs/conversation-flow.md](docs/conversation-flow.md), which was written
before the code and is kept authoritative.

### Weight Tracker

A personal-use bot for weekly weight tracking. `/start` subscribes you;
every Saturday it messages each active subscriber ("Last week: 84,2 kg") and
logs the numeric reply, answering with a trend message (down / up / steady
vs the previous entry). `/log` records a weigh-in anytime — even while
check-ins are paused with `/stop` — and `/history` shows the last 8 entries.
It is not published for general use; it runs for the operator and people
they invite.

## Repository layout

```
bots/
├── appointment/        # bot.py, handlers.py, dialogue.py, repository.py
└── weight/             # same structure
core/
├── config.py           # env loading/validation
├── db.py               # psycopg2 connection helper + query()
├── reply.py            # the Reply dataclass every dialogue returns
├── telegram.py         # keyboard/markup glue for handlers
└── webhook.py          # webhook secret check + Update parsing
tests/                  # unit tests (fake repositories) + gated integration tests
wsgi.py                 # ONE Flask app: one webhook route per bot + /tasks + /health
run_polling.py          # local dev entry point (appointment bot)
scripts/                # init_db.py, set_webhook.py (registers all bots)
schema.sql              # all tables, IF NOT EXISTS — safe to re-apply
```

Each bot follows the same internal shape: `bot.py` builds its telebot
instance and registers handlers once; `handlers.py` is thin Telegram glue;
`dialogue.py` is a pure state machine (no Telegram imports, no SQL) taking an
injected repository; `repository.py` owns all of that bot's SQL. One Flask
app (`wsgi.py`) exposes one webhook route per bot (`/webhook/<secret>`,
`/webhook-weight/<secret>`), each feeding its own telebot instance — so a
single free Render service hosts everything. Bots keep separate
conversation-state tables so a user talking to two bots never has one bot
overwrite the other's state.

## Scheduled triggers

The weight bot's Saturday check-in is not a background job inside the app.
Free-tier hosting can't run persistent schedulers reliably: the service spins
down after ~15 idle minutes, so an in-process scheduler (cron thread, APScheduler)
would simply not be running when its moment arrives. Instead, the app exposes
a protected endpoint — `POST /tasks/weekly-checkin/<CRON_SECRET>` — and an
external free cron service (cron-job.org, a GitHub Actions schedule, etc.)
calls it every Saturday morning. The call wakes the service if needed, the
endpoint does the work synchronously and returns `{"messaged": n}`, and the
secret path segment gets the same constant-time comparison as the Telegram
webhooks.

## Environment variables

| Variable                     | Required            | Purpose                                                      |
|------------------------------|---------------------|--------------------------------------------------------------|
| `APPOINTMENT_BOT_TOKEN`      | yes                 | Appointment bot's token from @BotFather                      |
| `WEIGHT_BOT_TOKEN`           | yes                 | Weight bot's token from @BotFather                           |
| `DATABASE_URL`               | yes                 | PostgreSQL connection string (this deployment uses Neon)     |
| `APPOINTMENT_WEBHOOK_SECRET` | webhook mode        | Random string in the appointment bot's webhook path          |
| `WEIGHT_WEBHOOK_SECRET`      | webhook mode        | Random string in the weight bot's webhook path               |
| `CRON_SECRET`                | webhook mode        | Protects `POST /tasks/weekly-checkin/<secret>`               |
| `PUBLIC_URL`                 | webhook mode        | Public https base URL, e.g. `https://….onrender.com`         |
| `BUSINESS_TIMEZONE`          | no (São Paulo)      | Fallback display timezone (IANA name) when a user has none   |
| `ADMIN_USER_ID`              | no                  | Telegram user id allowed to use the appointment admin commands |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
"Webhook mode" variables are validated at wsgi startup (fail fast); local
polling runs without them.

## Data storage

The weight tracker stores each user's weigh-in history — weight and
timestamp, keyed by Telegram user id — in the operator's PostgreSQL
database. The data is not shared with anyone and is used only to compute the
week-over-week messages the user sees; `/stop` pauses check-ins without
deleting anything, and a user can ask the operator to delete their history
entirely.

## Key design decisions

**Dialogue logic is pure and dependency-injected.**
Each bot's `handle_message(user_id, text, repo) -> Reply` touches neither
Telegram nor the database directly: the repository is passed in as a
parameter, and the returned `Reply` is a plain dataclass (text + keyboard
rows). That one seam is why the state machines have 110+ unit tests that run
in under half a second against in-memory fake repositories — every
transition, fallback, and race scenario tested without a database or
network — and why `handlers.py` stays a boring ~20-line adapter in both bots.

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
a Telegram update. Every webhook (and the cron endpoint) is therefore mounted
at a path containing a random 256-bit secret known only to Telegram (via
`setWebhook`) and the server. The comparison uses `hmac.compare_digest` to
avoid timing side-channels; wrong secrets get a 403 and are never parsed.

**Store UTC, display local time.**
All timestamps are stored in UTC (`timestamptz`); conversion to human time
happens only at display, in a single formatting function. Appointment-bot
users can pick their own display timezone with `/timezone` (presets or any
IANA name, validated with `zoneinfo`); without a setting, `BUSINESS_TIMEZONE`
applies. Every rendered time carries its zone — e.g. `Fri 31 Jul, 07:00
(UTC-3)` — and admin-typed slot times are interpreted as business-timezone
local and converted to UTC before storage, so the database never contains an
ambiguous timestamp.

**Polling in dev, webhook in prod.**
Long-polling (`run_polling.py`) needs no public URL, so local development
works behind any firewall with zero setup. Production uses webhooks, which
are push-based and let one small web service handle all bots. Each bot's
entry point imports its pre-wired instance from `bots/<name>/bot.py`
(handlers registered exactly once, `threaded=False` so handler exceptions
surface in the request that caused them, with full tracebacks logged to
stdout for Render's log tail). Telegram allows either mode per bot, never
both: `scripts/set_webhook.py --delete` switches back to polling.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # then fill in the tokens and DATABASE_URL
python scripts/init_db.py          # applies schema.sql + seed.sql
python run_polling.py              # appointment bot, long-polling
```

## Running tests

```powershell
# Unit tests (state machines + route guards — no real database needed)
python -m pytest

# Include repository integration tests against PostgreSQL
$env:TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/booking_test"
python -m pytest
```

Unit tests drive real message scripts through both bots' state machines
against in-memory fakes (`tests/fake_repository.py`,
`tests/fake_weight_repository.py`) and check the webhook/cron routes reject
wrong secrets. Integration tests in `tests/test_repository.py` verify the
transactional booking/cancelling behavior against a real PostgreSQL database;
they run only when `TEST_DATABASE_URL` is set and are skipped otherwise. They
drop and recreate all tables around every test — use a dedicated scratch
database.

## Deployment

The repo ships a `render.yaml` blueprint defining a free-plan Python web
service (build: `pip install -r requirements.txt`, start: `gunicorn wsgi:app`,
health check: `GET /health`).

1. In the Render dashboard: **New → Blueprint**, pick this repo, apply.
2. Fill in the prompted env vars (all `sync: false`, never stored in the
   repo) — see the table above.
3. Initialize the database once, locally, against the production
   `DATABASE_URL`: `python scripts/init_db.py`.
4. After the first deploy, register both bots' webhooks once:
   `python scripts/set_webhook.py` (with the production tokens, secrets, and
   `PUBLIC_URL` in the environment).
5. Point a scheduler (cron-job.org, a GitHub Actions cron, or a Render cron
   job) at `POST /tasks/weekly-checkin/<CRON_SECRET>` every Saturday morning.
6. Verify: `/health` returns `{"status": "ok"}` and both bots answer on
   Telegram.

Free-plan note: Render spins the service down after ~15 idle minutes; the
first message afterwards is answered with a cold-start delay (Telegram
retries delivery, so nothing is lost). An uptime monitor pinging `/health`
keeps it warm.
