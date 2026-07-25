# dialogue.py: conversation state machine (see docs/conversation-flow.md).
# Pure logic: receives (user_id, text, repo) and returns a Reply.
# No telebot imports, no SQL — data access goes through the injected repo,
# which lets tests pass a fake repository.

import logging
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.reply import Reply

logger = logging.getLogger(__name__)

# All timestamps are stored in UTC; displays convert to the user's saved
# timezone, falling back to this business timezone. Read directly from the
# environment rather than core.config, which demands APPOINTMENT_BOT_TOKEN/
# DATABASE_URL at import time — this module must stay importable with no
# configuration at all (see tests).
BUSINESS_TZ = ZoneInfo(os.getenv("BUSINESS_TIMEZONE", "America/Sao_Paulo"))


MAIN_MENU = [["Book an appointment"], ["My bookings"], ["Help"]]
CONFIRM_MENU = [["Confirm"], ["Change slot"], ["Cancel"]]
YES_NO = [["Yes", "No"]]
TIMEZONE_MENU = [["São Paulo", "Lisbon"], ["London", "New York"], ["UTC", "Other"]]

# Keyboard label (lowercased) -> IANA name. The accentless spelling is
# accepted for people who type instead of tapping.
TIMEZONE_PRESETS = {
    "são paulo": "America/Sao_Paulo",
    "sao paulo": "America/Sao_Paulo",
    "lisbon": "Europe/Lisbon",
    "london": "Europe/London",
    "new york": "America/New_York",
    "utc": "UTC",
}

GREETING = (
    "Hi! I can book appointments for you.\n"
    "Tap a button below, or send /mybookings to manage existing bookings."
)
HELP_TEXT = (
    "Here's what I can do:\n"
    "• Book an appointment — tap the button or send /start\n"
    "• /mybookings — list or cancel your bookings\n"
    "• /timezone — choose the timezone times are shown in\n"
    "• /cancel — abandon whatever we're doing"
)

MAX_SLOTS_SHOWN = 10

# Admin-only commands: checked after global commands, before state logic.
# For non-admins these fall through to the normal state fallback, so their
# existence is never revealed.
ADMIN_COMMANDS = ("/addslot", "/slots", "/appointments")
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATETIME_EXAMPLE = "2026-08-01 14:00"


def handle_message(user_id, text, repo, user_name="Guest", admin_user_id=None):
    """Route one incoming message through the state machine, return a Reply."""
    state_before = _current_state(repo, user_id)
    reply = _dispatch(user_id, text, repo, user_name, admin_user_id)
    state_after = _current_state(repo, user_id)
    logger.info("user %s: state %s -> %s", user_id, state_before, state_after)
    return reply


def _current_state(repo, user_id):
    row = repo.get_state(user_id)
    return row["state"] if row else "idle"


def _dispatch(user_id, text, repo, user_name, admin_user_id=None):
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
    if lowered == "/timezone":
        return _show_timezone_menu(user_id, repo)

    if lowered in ADMIN_COMMANDS:
        reply = _try_admin_command(user_id, lowered, repo, admin_user_id)
        if reply is not None:
            return reply
        # Non-admin sender: fall through to normal state handling, so the
        # command gets the ordinary fallback re-prompt for the current state.

    row = repo.get_state(user_id)
    state = row["state"] if row else "idle"
    context = (row.get("context") or {}) if row else {}

    # Handlers receive the original (stripped) text: some inputs are
    # case-sensitive, e.g. IANA timezone names.
    handler = _STATE_HANDLERS.get(state, _handle_idle)
    return handler(user_id, text, repo, context, user_name)


# --- per-state handlers -------------------------------------------------------

def _handle_idle(user_id, text, repo, context, user_name):
    lowered = text.lower()
    if re.search(r"\bbook\b", lowered):
        return _show_services(user_id, repo)
    if lowered in ("help", "/help"):
        return Reply(HELP_TEXT, MAIN_MENU)
    return Reply(
        "I didn't catch that. Tap a button below, or send /start.", MAIN_MENU
    )


def _handle_choosing_service(user_id, text, repo, context, user_name):
    options = context.get("service_options", [])
    service_id = _pick(text, options)
    if service_id is None:
        return Reply(
            f"Please send a number between 1 and {len(options)} to pick a "
            "service, or /cancel.",
            _number_keyboard(len(options)),
        )
    return _show_slots(user_id, repo, service_id)


def _handle_choosing_slot(user_id, text, repo, context, user_name):
    service_id = context["service_id"]
    options = context.get("slot_options", [])
    slot_id = _pick(text, options)
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
        f"• When: {_format_slot(slot['starts_at'], _user_tz(repo, user_id))}\n"
        f"• Name: {user_name}",
        CONFIRM_MENU,
    )


def _handle_confirming(user_id, text, repo, context, user_name):
    lowered = text.lower()
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
            f"{_format_slot(appointment['starts_at'], _user_tz(repo, user_id))} "
            f"under {user_name}.\n"
            "Book another?",
            YES_NO,
        )
    if lowered == "change slot":
        return _show_slots(user_id, repo, service_id)
    if lowered == "cancel":
        repo.clear_state(user_id)
        return Reply("Okay, cancelled.", MAIN_MENU)
    return Reply("Please choose: Confirm, Change slot, or Cancel.", CONFIRM_MENU)


def _handle_post_booking(user_id, text, repo, context, user_name):
    lowered = text.lower()
    if lowered == "yes":
        return _show_services(user_id, repo)
    if lowered == "no":
        repo.clear_state(user_id)
        return Reply("See you soon! Send /start anytime.", None)
    return Reply("Book another? (Yes / No)", YES_NO)


def _handle_managing_bookings(user_id, text, repo, context, user_name):
    options = context.get("appointment_options", [])
    appointment_id = _pick(text, options)
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
        f"{_format_slot(appointment['starts_at'], _user_tz(repo, user_id))}? "
        "(Yes / No)",
        YES_NO,
    )


def _handle_confirm_cancel(user_id, text, repo, context, user_name):
    lowered = text.lower()
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


# --- timezone selection ---------------------------------------------------------

def _show_timezone_menu(user_id, repo):
    current = repo.get_user_timezone(user_id) or f"{BUSINESS_TZ.key} (default)"
    repo.set_state(user_id, "choosing_timezone", {})
    return Reply(
        f"Times are currently shown in {current}.\n"
        "Pick a timezone, or Other to type one:",
        TIMEZONE_MENU,
    )


def _handle_choosing_timezone(user_id, text, repo, context, user_name):
    lowered = text.lower()
    if lowered == "other":
        repo.set_state(user_id, "typing_timezone", {})
        return Reply(
            "Type an IANA timezone name, e.g. Europe/Berlin or "
            "America/Mexico_City.",
            None,
        )
    if lowered in TIMEZONE_PRESETS:
        return _save_timezone(user_id, repo, TIMEZONE_PRESETS[lowered])
    return Reply(
        "Please pick one of the options, or Other to type a timezone name.",
        TIMEZONE_MENU,
    )


def _handle_typing_timezone(user_id, text, repo, context, user_name):
    try:
        tz = ZoneInfo(text)
    except Exception:
        return Reply(
            f"I don't know the timezone {text!r}. Use an IANA name like "
            "Europe/Berlin or America/Mexico_City — capitalization matters. "
            "Try again, or /cancel.",
            None,
        )
    return _save_timezone(user_id, repo, tz.key)


def _save_timezone(user_id, repo, tz_name):
    repo.set_user_timezone(user_id, tz_name)
    repo.clear_state(user_id)
    now_local = datetime.now(ZoneInfo(tz_name))
    return Reply(
        f"Saved — times will be shown in {tz_name} ({_tz_label(now_local)}).",
        MAIN_MENU,
    )


# --- admin commands (entry is gated on admin_user_id) --------------------------

def _try_admin_command(user_id, command, repo, admin_user_id):
    """Handle an admin command, or return None to fall through to state logic."""
    if admin_user_id is None:
        return Reply("Admin commands are not configured on this bot.", MAIN_MENU)
    if user_id != admin_user_id:
        return None
    if command == "/addslot":
        return _admin_show_services(user_id, repo)
    if command == "/slots":
        return _admin_list_slots(user_id, repo)
    return _admin_list_appointments(user_id, repo)


def _admin_show_services(user_id, repo):
    services = repo.list_services()
    if not services:
        repo.clear_state(user_id)
        return Reply("No active services to add slots for.", MAIN_MENU)
    lines = [f"{i}. {s['name']}" for i, s in enumerate(services, 1)]
    repo.set_state(
        user_id, "admin_choosing_service",
        {"service_options": [s["id"] for s in services]},
    )
    return Reply(
        "Add a slot for which service?\n" + "\n".join(lines),
        _number_keyboard(len(services)),
    )


def _handle_admin_choosing_service(user_id, text, repo, context, user_name):
    options = context.get("service_options", [])
    service_id = _pick(text, options)
    if service_id is None:
        return Reply(
            f"Please send a number between 1 and {len(options)} to pick a "
            "service, or /cancel.",
            _number_keyboard(len(options)),
        )
    repo.set_state(user_id, "admin_typing_datetime", {"service_id": service_id})
    return Reply(
        f"Send the date and time for the new {_service_name(repo, service_id)} "
        f"slot in {BUSINESS_TZ.key} time, format: {DATETIME_EXAMPLE}",
        None,
    )


def _handle_admin_typing_datetime(user_id, text, repo, context, user_name):
    service_id = context["service_id"]
    try:
        # Typed times are business-timezone local; storage is UTC.
        starts_at = datetime.strptime(text, DATETIME_FORMAT).replace(
            tzinfo=BUSINESS_TZ
        )
    except ValueError:
        return Reply(
            "I couldn't read that as a date and time. "
            f"Use the format {DATETIME_EXAMPLE} (24-hour), or /cancel.",
            None,
        )
    if starts_at <= datetime.now(timezone.utc):
        return Reply(
            "That time is in the past — send a future date and time, or /cancel.",
            None,
        )
    repo.create_slot(service_id, starts_at.astimezone(timezone.utc))
    name = _service_name(repo, service_id)
    # Stay in this state so several slots can be added back to back.
    return Reply(
        f"Added: {name} — {_format_slot(starts_at, _user_tz(repo, user_id))}.\n"
        f"Send another time for {name}, or /cancel to finish.",
        None,
    )


def _admin_list_slots(user_id, repo):
    repo.clear_state(user_id)
    slots = repo.list_upcoming_slots()
    if not slots:
        return Reply("No upcoming slots.", MAIN_MENU)
    tz = _user_tz(repo, user_id)
    lines = [
        f"{_format_slot(s['starts_at'], tz)} — {s['service_name']} — "
        f"{'booked' if s['is_booked'] else 'free'}"
        for s in slots
    ]
    return Reply("Upcoming slots:\n" + "\n".join(lines), MAIN_MENU)


def _admin_list_appointments(user_id, repo):
    repo.clear_state(user_id)
    appointments = repo.list_upcoming_appointments()
    if not appointments:
        return Reply("No upcoming appointments.", MAIN_MENU)
    tz = _user_tz(repo, user_id)
    lines = [
        f"{_format_slot(a['starts_at'], tz)} — {a['service_name']} — "
        f"{a['customer_name']}"
        for a in appointments
    ]
    return Reply("Upcoming appointments:\n" + "\n".join(lines), MAIN_MENU)


_STATE_HANDLERS = {
    "idle": _handle_idle,
    "choosing_service": _handle_choosing_service,
    "choosing_slot": _handle_choosing_slot,
    "confirming": _handle_confirming,
    "post_booking": _handle_post_booking,
    "managing_bookings": _handle_managing_bookings,
    "confirm_cancel": _handle_confirm_cancel,
    "choosing_timezone": _handle_choosing_timezone,
    "typing_timezone": _handle_typing_timezone,
    "admin_choosing_service": _handle_admin_choosing_service,
    "admin_typing_datetime": _handle_admin_typing_datetime,
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
    tz = _user_tz(repo, user_id)
    lines = [
        f"{i}. {_format_slot(s['starts_at'], tz)}" for i, s in enumerate(slots, 1)
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
    tz = _user_tz(repo, user_id)
    lines = [
        f"{i}. {a['service_name']} — {_format_slot(a['starts_at'], tz)}"
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

def _pick(text, options):
    """Map a typed number onto the ID list stored in context, else None."""
    if not text.isdigit():
        return None
    n = int(text)
    if not 1 <= n <= len(options):
        return None
    return options[n - 1]


def _find(rows, row_id):
    return next((r for r in rows if r["id"] == row_id), None)


def _service_name(repo, service_id):
    service = _find(repo.list_services(), service_id)
    return service["name"] if service else "your appointment"


def _user_tz(repo, user_id):
    """The user's saved display timezone, else the business default."""
    name = repo.get_user_timezone(user_id)
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("user %s has invalid saved timezone %r", user_id, name)
    return BUSINESS_TZ


def _format_slot(starts_at, tz):
    """Render a stored (UTC) timestamp in the given display timezone.

    Every user-facing datetime goes through here — keep display changes in
    this one place. Naive input is treated as UTC (the storage convention).
    """
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    local = starts_at.astimezone(tz)
    # Manual day to avoid zero-padding ("Mon 7 Jul", not "Mon 07 Jul");
    # strftime has no portable no-pad flag on Windows.
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M} ({_tz_label(local)})"


def _tz_label(local):
    """Timezone suffix: tzdata's abbreviation if it has letters (CET, PST),
    else the UTC offset (modern tzdata reports e.g. Sao Paulo as just "-03")."""
    name = local.tzname() or ""
    if any(c.isalpha() for c in name):
        return name
    minutes = int(local.utcoffset().total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def _number_keyboard(count):
    numbers = [str(n) for n in range(1, count + 1)]
    return [numbers[i:i + 3] for i in range(0, len(numbers), 3)]


def _prefixed(prefix, text, keyboard):
    return Reply(f"{prefix}\n\n{text}" if prefix else text, keyboard)
