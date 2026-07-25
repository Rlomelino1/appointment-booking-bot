# dialogue.py: conversation state machine (see docs/conversation-flow.md).
# Pure logic: receives (user_id, text, repo) and returns a Reply.
# No telebot imports, no SQL — data access goes through the injected repo,
# which lets tests pass a fake repository.

import re
from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    keyboard: list[list[str]] | None = None


MAIN_MENU = [["Book an appointment"], ["My bookings"], ["Help"]]
CONFIRM_MENU = [["Confirm"], ["Change slot"], ["Cancel"]]
YES_NO = [["Yes", "No"]]

GREETING = (
    "Hi! I can book appointments for you.\n"
    "Tap a button below, or send /mybookings to manage existing bookings."
)
HELP_TEXT = (
    "Here's what I can do:\n"
    "• Book an appointment — tap the button or send /start\n"
    "• /mybookings — list or cancel your bookings\n"
    "• /cancel — abandon whatever we're doing"
)

MAX_SLOTS_SHOWN = 10


def handle_message(user_id, text, repo, user_name="Guest"):
    """Route one incoming message through the state machine, return a Reply."""
    text = (text or "").strip()

    # Global commands win over state logic in every state.
    lowered = text.lower()
    if lowered == "/start":
        repo.clear_state(user_id)
        return Reply(GREETING, MAIN_MENU)
    if lowered == "/cancel":
        repo.clear_state(user_id)
        return Reply("Okay, cancelled.", MAIN_MENU)
    if lowered in ("/mybookings", "my bookings"):
        return _show_bookings(user_id, repo)

    row = repo.get_state(user_id)
    state = row["state"] if row else "idle"
    context = (row.get("context") or {}) if row else {}

    handler = _STATE_HANDLERS.get(state, _handle_idle)
    return handler(user_id, lowered, repo, context, user_name)


# --- per-state handlers -------------------------------------------------------

def _handle_idle(user_id, lowered, repo, context, user_name):
    if re.search(r"\bbook\b", lowered):
        return _show_services(user_id, repo)
    if lowered in ("help", "/help"):
        return Reply(HELP_TEXT, MAIN_MENU)
    return Reply(
        "I didn't catch that. Tap a button below, or send /start.", MAIN_MENU
    )


def _handle_choosing_service(user_id, lowered, repo, context, user_name):
    options = context.get("service_options", [])
    service_id = _pick(lowered, options)
    if service_id is None:
        return Reply(
            f"Please send a number between 1 and {len(options)} to pick a "
            "service, or /cancel.",
            _number_keyboard(len(options)),
        )
    return _show_slots(user_id, repo, service_id)


def _handle_choosing_slot(user_id, lowered, repo, context, user_name):
    service_id = context["service_id"]
    options = context.get("slot_options", [])
    slot_id = _pick(lowered, options)
    if slot_id is None:
        return Reply(
            f"Please send a number between 1 and {len(options)} to pick a "
            "time, or /cancel.",
            _number_keyboard(len(options)),
        )

    # Re-fetch to render the summary; a slot missing from the fresh list was
    # taken between display and pick — same apology as the confirm-time race.
    slot = _find(repo.list_available_slots(service_id), slot_id)
    if slot is None:
        return _show_slots(
            user_id, repo, service_id, prefix="Sorry — that slot was just taken."
        )

    repo.set_state(
        user_id, "confirming", {"service_id": service_id, "slot_id": slot_id}
    )
    return Reply(
        "Here's your booking:\n"
        f"• Service: {_service_name(repo, service_id)}\n"
        f"• When: {_format_slot(slot['starts_at'])}\n"
        f"• Name: {user_name}",
        CONFIRM_MENU,
    )


def _handle_confirming(user_id, lowered, repo, context, user_name):
    service_id = context["service_id"]
    if lowered == "confirm":
        try:
            appointment = repo.book_slot(user_id, context["slot_id"], user_name)
        except repo.SlotAlreadyBookedError:
            return _show_slots(
                user_id, repo, service_id,
                prefix="Sorry — that slot was just taken.",
            )
        repo.set_state(user_id, "post_booking", {})
        return Reply(
            f"✅ Booked! {_service_name(repo, service_id)} on "
            f"{_format_slot(appointment['starts_at'])} under {user_name}.\n"
            "Book another?",
            YES_NO,
        )
    if lowered == "change slot":
        return _show_slots(user_id, repo, service_id)
    if lowered == "cancel":
        repo.clear_state(user_id)
        return Reply("Okay, cancelled.", MAIN_MENU)
    return Reply("Please choose: Confirm, Change slot, or Cancel.", CONFIRM_MENU)


def _handle_post_booking(user_id, lowered, repo, context, user_name):
    if lowered == "yes":
        return _show_services(user_id, repo)
    if lowered == "no":
        repo.clear_state(user_id)
        return Reply("See you soon! Send /start anytime.", None)
    return Reply("Book another? (Yes / No)", YES_NO)


def _handle_managing_bookings(user_id, lowered, repo, context, user_name):
    options = context.get("appointment_options", [])
    appointment_id = _pick(lowered, options)
    if appointment_id is None:
        return Reply(
            f"Send a number between 1 and {len(options)} to cancel a booking, "
            "or /start for the menu.",
            _number_keyboard(len(options)),
        )
    appointment = _find(repo.list_appointments_for_user(user_id), appointment_id)
    if appointment is None:
        return _show_bookings(
            user_id, repo, prefix="That booking no longer exists."
        )
    repo.set_state(user_id, "confirm_cancel", {"appointment_id": appointment_id})
    return Reply(
        f"Cancel {appointment['service_name']} on "
        f"{_format_slot(appointment['starts_at'])}? (Yes / No)",
        YES_NO,
    )


def _handle_confirm_cancel(user_id, lowered, repo, context, user_name):
    if lowered == "yes":
        try:
            repo.cancel_appointment(context["appointment_id"], user_id)
        except repo.AppointmentNotFoundError:
            repo.clear_state(user_id)
            return Reply("That booking was already cancelled.", MAIN_MENU)
        repo.clear_state(user_id)
        return Reply("Cancelled.", MAIN_MENU)
    if lowered == "no":
        repo.clear_state(user_id)
        return Reply("Kept it.", MAIN_MENU)
    return Reply("Please answer Yes or No.", YES_NO)


_STATE_HANDLERS = {
    "idle": _handle_idle,
    "choosing_service": _handle_choosing_service,
    "choosing_slot": _handle_choosing_slot,
    "confirming": _handle_confirming,
    "post_booking": _handle_post_booking,
    "managing_bookings": _handle_managing_bookings,
    "confirm_cancel": _handle_confirm_cancel,
}


# --- shared steps -------------------------------------------------------------

def _show_services(user_id, repo, prefix=""):
    """Show the numbered service list and enter choosing_service."""
    services = repo.list_services()
    if not services:
        repo.clear_state(user_id)
        return _prefixed(
            prefix, "Sorry, no services are available right now.", MAIN_MENU
        )
    lines = [
        f"{i}. {s['name']} ({s['duration_minutes']} min)"
        for i, s in enumerate(services, 1)
    ]
    repo.set_state(
        user_id, "choosing_service",
        {"service_options": [s["id"] for s in services]},
    )
    return _prefixed(
        prefix,
        "Which service would you like?\n" + "\n".join(lines),
        _number_keyboard(len(services)),
    )


def _show_slots(user_id, repo, service_id, prefix=""):
    """Show the numbered slot list and enter choosing_slot."""
    slots = repo.list_available_slots(service_id)[:MAX_SLOTS_SHOWN]
    if not slots:
        return _show_services(
            user_id, repo, prefix="No free slots for this service right now."
        )
    lines = [
        f"{i}. {_format_slot(s['starts_at'])}" for i, s in enumerate(slots, 1)
    ]
    repo.set_state(
        user_id, "choosing_slot",
        {"service_id": service_id, "slot_options": [s["id"] for s in slots]},
    )
    return _prefixed(
        prefix,
        "Pick a time:\n" + "\n".join(lines),
        _number_keyboard(len(slots)),
    )


def _show_bookings(user_id, repo, prefix=""):
    """Show the user's confirmed bookings and enter managing_bookings."""
    appointments = repo.list_appointments_for_user(user_id)
    if not appointments:
        repo.clear_state(user_id)
        return _prefixed(prefix, "You have no bookings yet.", MAIN_MENU)
    lines = [
        f"{i}. {a['service_name']} — {_format_slot(a['starts_at'])}"
        for i, a in enumerate(appointments, 1)
    ]
    repo.set_state(
        user_id, "managing_bookings",
        {"appointment_options": [a["id"] for a in appointments]},
    )
    return _prefixed(
        prefix,
        "Your bookings:\n" + "\n".join(lines)
        + "\n\nSend a number to cancel a booking, or /start for the menu.",
        _number_keyboard(len(appointments)),
    )


# --- small helpers ------------------------------------------------------------

def _pick(lowered, options):
    """Map a typed number onto the ID list stored in context, else None."""
    if not lowered.isdigit():
        return None
    n = int(lowered)
    if not 1 <= n <= len(options):
        return None
    return options[n - 1]


def _find(rows, row_id):
    return next((r for r in rows if r["id"] == row_id), None)


def _service_name(repo, service_id):
    service = _find(repo.list_services(), service_id)
    return service["name"] if service else "your appointment"


def _format_slot(starts_at):
    # Manual day to avoid zero-padding ("Mon 7 Jul", not "Mon 07 Jul");
    # strftime has no portable no-pad flag on Windows.
    return f"{starts_at:%a} {starts_at.day} {starts_at:%b}, {starts_at:%H:%M}"


def _number_keyboard(count):
    numbers = [str(n) for n in range(1, count + 1)]
    return [numbers[i:i + 3] for i in range(0, len(numbers), 3)]


def _prefixed(prefix, text, keyboard):
    return Reply(f"{prefix}\n\n{text}" if prefix else text, keyboard)
