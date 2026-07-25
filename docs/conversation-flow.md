# Conversation flow design

This document is the source of truth for the bot's dialogue state machine.
Each Telegram user has at most one row in `conversation_state`
(`telegram_user_id`, `state`, `context` jsonb). Every incoming message is
interpreted according to the user's current state. The dialogue logic in
`bots/appointment/dialogue.py` is pure: it receives (user_id, text, repo) and returns a
Reply — no Telegram calls, no SQL of its own.

## States

| State               | Meaning                                    | `context` contents                      |
|---------------------|--------------------------------------------|-----------------------------------------|
| `idle`              | No active flow (default; row may not exist)| `{}`                                    |
| `choosing_service`  | Service list shown, awaiting a pick        | `{"service_options": [ids]}`            |
| `choosing_slot`     | Slot list shown, awaiting a pick           | `{"service_id": n, "slot_options": [ids]}` |
| `confirming`        | Summary shown, awaiting confirm/change     | `{"service_id": n, "slot_id": n}`       |
| `post_booking`      | Booking done, offered "Book another?"      | `{}`                                    |
| `managing_bookings` | Appointment list shown, awaiting a pick    | `{"appointment_options": [ids]}`        |
| `confirm_cancel`    | Asked "really cancel #N?"                  | `{"appointment_id": n}`                 |
| `choosing_timezone` | Timezone keyboard shown, awaiting a pick   | `{}`                                    |
| `typing_timezone`   | Awaiting a typed IANA timezone name        | `{}`                                    |
| `admin_choosing_service` | Admin: /addslot service list shown, awaiting a pick | `{"service_options": [ids]}` |
| `admin_typing_datetime`  | Admin: awaiting the new slot's date/time             | `{"service_id": n}`          |

**Customer name:** never asked. It is taken automatically from the Telegram
message metadata (`from.first_name` + `from.last_name` when present) at the
moment the booking is written, and shown in the confirmation summary.

**Why option lists live in context:** when the bot shows "1. Haircut,
2. Massage", the reply "2" is only meaningful relative to that exact list.
Storing the IDs in `context` at display time means the number maps to the ID
the user actually saw, even if the database contents change in between.

## Global commands (valid in every state, checked before state logic)

| Input         | Effect                                                        |
|---------------|---------------------------------------------------------------|
| `/start`      | Clear state → `idle`; greet; show main menu keyboard: **Book an appointment** / **My bookings** / **Help** |
| `/cancel`     | Clear state → `idle`; reply "Okay, cancelled."                |
| `/mybookings` | List the user's confirmed appointments → `managing_bookings`  |
| `/timezone`   | Show the timezone picker keyboard → `choosing_timezone`       |

## Timezone selection

All timestamps are stored in UTC. Displays convert to the user's saved
timezone (`user_settings.timezone`) when present, else to `BUSINESS_TIMEZONE`
(default America/Sao_Paulo) — one formatting function does this everywhere,
and always appends the zone, e.g. "Mon 27 Jul, 14:00 (UTC-3)".

1. `/timezone` → shows the current setting and a keyboard:
   **São Paulo / Lisbon / London / New York / UTC / Other** → `choosing_timezone`.
2. **choosing_timezone**
   - a preset → save its IANA name → "Saved — times will be shown in …" → `idle`.
   - **Other** → "Type an IANA timezone name…" → `typing_timezone`.
   - anything else → fallback re-prompt with the keyboard.
3. **typing_timezone** — input validated with `zoneinfo.ZoneInfo`
   (case-sensitive, so this state receives the user's original text):
   - valid → save → `idle`.
   - invalid → helpful re-prompt naming the expected format, state unchanged.

## Admin commands (checked after global commands, before state logic)

Admin access is a single Telegram user id from the optional `ADMIN_USER_ID`
env var, injected into `handle_message` as a parameter (like the repo).
The commands are `/addslot`, `/slots`, `/appointments`.

| Sender                       | Effect                                                     |
|------------------------------|------------------------------------------------------------|
| `ADMIN_USER_ID` unset        | "Admin commands are not configured on this bot."           |
| the admin                    | Command runs (below)                                       |
| anyone else                  | Falls through to the current state's normal fallback — the commands' existence is never revealed |

- `/addslot` → numbered service list → `admin_choosing_service`
  → a number within range → "Send the date and time … format: 2026-08-01 14:00"
  → `admin_typing_datetime` with `service_id`
  → input must parse as `YYYY-MM-DD HH:MM` **and** be in the future, else a
    re-prompt (state unchanged); the typed time is interpreted as
    business-timezone local time and stored as UTC
  → on success the slot is created and the state **stays**
    `admin_typing_datetime`, so several slots can be added back to back;
    `/cancel` finishes.
- `/slots` → all upcoming slots as "{when} — {service} — booked/free" → `idle`.
- `/appointments` → all users' upcoming confirmed appointments as
  "{when} — {service} — {customer name}" → `idle`.

## Fallback (every state)

Any input that matches neither a global command nor the current state's
expected input: re-send a short prompt showing the valid options for the
current state. State and context are unchanged. The bot never crashes on
input and never stays silent.

## Booking flow transitions

1. **idle** — "Book an appointment" (or the word "book")
   → fetch active services → if none: apologize, stay `idle`
   → else show numbered services as a reply keyboard
   → `choosing_service` with `service_options`.

2. **choosing_service** — a number within range
   → fetch available future slots for that service
   → if none: "No free slots for this service right now", re-show services, stay `choosing_service` (refresh `service_options`)
   → else show numbered slots (max 10, soonest first) formatted in the
     user's display timezone (see "Timezone selection"),
     e.g. "Mon 27 Jul, 14:00 (UTC-3)" — storage is always UTC, conversion
     happens only at display time in one formatting function
   → `choosing_slot` with `service_id` + `slot_options`.

3. **choosing_slot** — a number within range
   → show summary: service, date/time, name (from Telegram)
   → keyboard: **Confirm** / **Change slot** / **Cancel**
   → `confirming` with `service_id` + `slot_id`.

4. **confirming**
   - **Confirm** → attempt transactional booking (`book_slot`):
     - success → "✅ Booked! {service} on {slot} under {name}." →
       "Book another?" keyboard **Yes** / **No** → `post_booking`.
     - slot already taken (race) → "Sorry — that slot was just taken."
       → re-fetch and show slots → back to `choosing_slot`.
   - **Change slot** → re-fetch and show slots → `choosing_slot`.
   - **Cancel** → clear state → `idle`.

5. **post_booking**
   - **Yes** → same as step 1 (fresh service list) → `choosing_service`.
   - **No** → "See you soon! Send /start anytime." → clear state → `idle`.
   - anything else → fallback re-prompt (Yes / No).

## Managing bookings

1. `/mybookings` (or "My bookings" menu button)
   → fetch the user's confirmed appointments
   → if none: "You have no bookings yet." → `idle`
   → else numbered list ("1. Haircut — Mon 27 Jul, 14:00 (UTC-3)") with prompt
     "Send a number to cancel a booking, or /start for the menu"
   → `managing_bookings` with `appointment_options`.

2. **managing_bookings** — a number within range
   → "Cancel {service} on {slot}? (Yes / No)"
   → `confirm_cancel` with `appointment_id`.

3. **confirm_cancel**
   - **Yes** → `cancel_appointment` (sets status='cancelled', frees the slot,
     one transaction) → "Cancelled." → `idle`.
   - **No** → "Kept it." → `idle`.
   - anything else → fallback re-prompt (Yes / No).

## Edge cases checklist

- [ ] Out-of-range number at any choosing state → fallback, state unchanged
- [ ] Slot-taken race at confirm → apologetic re-offer, no partial writes
- [ ] `/cancel` mid-flow at every state → always lands cleanly in `idle`
- [ ] Empty services / empty slots / empty bookings → friendly message, no crash
- [ ] Unknown first message from a brand-new user (no state row) → treated as `idle`
- [ ] Cancelling a booking twice (stale list) → `cancel_appointment` no-ops gracefully
