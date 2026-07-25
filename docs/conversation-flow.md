# Conversation flow design

This document is the source of truth for the bot's dialogue state machine.
Each Telegram user has at most one row in `conversation_state`
(`telegram_user_id`, `state`, `context` jsonb). Every incoming message is
interpreted according to the user's current state. The dialogue logic in
`app/dialogue.py` is pure: it receives (user_id, text, repo) and returns a
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
   → else show numbered slots formatted "Mon 27 Jul, 14:00" (max 10, soonest first)
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
   → else numbered list ("1. Haircut — Mon 27 Jul, 14:00") with prompt
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
