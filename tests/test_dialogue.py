# Unit tests for the dialogue state machine (app/dialogue.py).
# Everything runs against tests/fake_repository.FakeRepository — no database,
# no Telegram. States are reached by driving real messages through
# handle_message, so these tests exercise the same paths users do.

from datetime import datetime, timedelta, timezone

import pytest

from app.dialogue import handle_message
from tests.fake_repository import FakeRepository

USER = 111
NOW = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)  # a Friday
# Slots are stored in UTC and displayed in BUSINESS_TIMEZONE
# (default America/Sao_Paulo, UTC-3): 17:00 UTC renders as 14:00.
SLOT_LABEL = "Mon 27 Jul, 14:00 (UTC-3)"


@pytest.fixture
def repo():
    r = FakeRepository()
    haircut = r.add_service("Haircut", 30)
    massage = r.add_service("Massage", 60)
    r.add_slot(haircut, NOW + timedelta(days=3, hours=8))  # Mon 27 Jul, 17:00 UTC
    r.add_slot(haircut, NOW + timedelta(days=4))
    r.add_slot(massage, NOW + timedelta(days=5))
    return r


def send(repo, text):
    return handle_message(USER, text, repo, user_name="Ana Silva")


def state_of(repo, user_id=USER):
    row = repo.get_state(user_id)
    return row["state"] if row else "idle"


# Message scripts that drive a fresh user into each non-idle state.
# The managing states first create a booking through the normal flow.
SCRIPTS = {
    "choosing_service": ["book"],
    "choosing_slot": ["book", "1"],
    "confirming": ["book", "1", "1"],
    "post_booking": ["book", "1", "1", "Confirm"],
    "managing_bookings": ["book", "1", "1", "Confirm", "No", "/mybookings"],
    "confirm_cancel": ["book", "1", "1", "Confirm", "No", "/mybookings", "1"],
}


def drive_to(repo, state):
    for text in SCRIPTS[state]:
        send(repo, text)
    assert state_of(repo) == state  # guard: the script really got us there
    return repo


# --- happy path -----------------------------------------------------------

def test_happy_path_start_to_confirmed_booking(repo):
    reply = send(repo, "/start")
    assert "book" in reply.text.lower()
    assert ["Book an appointment"] in reply.keyboard
    assert state_of(repo) == "idle"

    reply = send(repo, "Book an appointment")
    assert "1. Haircut (30 min)" in reply.text
    assert "2. Massage (60 min)" in reply.text
    assert reply.keyboard == [["1", "2"]]
    assert state_of(repo) == "choosing_service"

    reply = send(repo, "1")  # Haircut
    assert f"1. {SLOT_LABEL}" in reply.text
    assert state_of(repo) == "choosing_slot"

    reply = send(repo, "1")
    assert "Haircut" in reply.text
    assert SLOT_LABEL in reply.text
    assert "Ana Silva" in reply.text
    assert reply.keyboard == [["Confirm"], ["Change slot"], ["Cancel"]]
    assert state_of(repo) == "confirming"

    reply = send(repo, "Confirm")
    assert reply.text.startswith(
        f"✅ Booked! Haircut on {SLOT_LABEL} under Ana Silva."
    )
    assert reply.keyboard == [["Yes", "No"]]
    assert state_of(repo) == "post_booking"
    assert repo.appointments[0]["status"] == "confirmed"
    assert repo.slots[repo.appointments[0]["slot_id"]]["is_booked"] is True

    reply = send(repo, "No")
    assert "See you soon" in reply.text
    assert reply.keyboard is None  # keyboard removed
    assert state_of(repo) == "idle"


# --- /cancel at every intermediate state -----------------------------------

@pytest.mark.parametrize("state", list(SCRIPTS))
def test_cancel_lands_in_idle(repo, state):
    drive_to(repo, state)
    reply = send(repo, "/cancel")
    assert reply.text == "Okay, cancelled."
    assert state_of(repo) == "idle"


# --- fallback: invalid input never changes state ----------------------------

@pytest.mark.parametrize("state", ["idle"] + list(SCRIPTS))
@pytest.mark.parametrize("bad_input", ["xyzzy", "99", "0", ""])
def test_invalid_input_reprompts_and_keeps_state(repo, state, bad_input):
    if state != "idle":
        drive_to(repo, state)
    before = repo.get_state(USER)

    reply = send(repo, bad_input)

    assert reply.text  # never silent
    assert reply.keyboard  # always re-offers tappable options
    assert repo.get_state(USER) == before  # state AND context untouched


def test_fallback_texts_show_valid_options(repo):
    drive_to(repo, "choosing_service")
    assert "between 1 and 2" in send(repo, "99").text

    repo.clear_state(USER)
    drive_to(repo, "confirming")
    assert "Confirm, Change slot, or Cancel" in send(repo, "what?").text

    repo.clear_state(USER)
    drive_to(repo, "post_booking")
    assert "Yes / No" in send(repo, "maybe").text


# --- slot-taken races -------------------------------------------------------

def take_first_haircut_slot(repo):
    """Simulate another user grabbing the slot the test user is looking at."""
    slot_id = repo.get_state(USER)["context"].get("slot_id") or \
        repo.get_state(USER)["context"]["slot_options"][0]
    repo.slots[slot_id]["is_booked"] = True
    return slot_id


def test_slot_taken_race_at_confirm_reoffers_slots(repo):
    drive_to(repo, "confirming")
    taken = take_first_haircut_slot(repo)

    reply = send(repo, "Confirm")

    assert "just taken" in reply.text
    assert "Pick a time" in reply.text
    assert state_of(repo) == "choosing_slot"
    assert taken not in repo.get_state(USER)["context"]["slot_options"]
    assert not repo.appointments  # no partial writes


def test_slot_taken_race_at_pick_reoffers_slots(repo):
    drive_to(repo, "choosing_slot")
    taken = take_first_haircut_slot(repo)

    reply = send(repo, "1")  # picks the now-taken slot

    assert "just taken" in reply.text
    assert state_of(repo) == "choosing_slot"
    assert taken not in repo.get_state(USER)["context"]["slot_options"]


# --- empty lists ------------------------------------------------------------

def test_no_services(repo):
    repo.services = []
    reply = send(repo, "book")
    assert "no services" in reply.text.lower()
    assert state_of(repo) == "idle"


def test_no_slots_reshows_services(repo):
    for slot in repo.slots.values():
        slot["is_booked"] = True
    send(repo, "book")
    reply = send(repo, "2")  # Massage, all booked
    assert "No free slots" in reply.text
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


def test_mybookings_empty(repo):
    reply = send(repo, "/mybookings")
    assert reply.text == "You have no bookings yet."
    assert state_of(repo) == "idle"


def test_slots_capped_at_ten(repo):
    massage = next(s["id"] for s in repo.services if s["name"] == "Massage")
    for hours in range(15):
        repo.add_slot(massage, NOW + timedelta(days=10, hours=hours))
    send(repo, "book")
    reply = send(repo, "2")  # Massage
    assert len(repo.get_state(USER)["context"]["slot_options"]) == 10
    assert "11." not in reply.text


# --- remaining transitions ---------------------------------------------------

def test_post_booking_yes_restarts_flow(repo):
    drive_to(repo, "post_booking")
    reply = send(repo, "Yes")
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


def test_change_slot_reoffers_slots(repo):
    drive_to(repo, "confirming")
    reply = send(repo, "Change slot")
    assert "Pick a time" in reply.text
    assert state_of(repo) == "choosing_slot"


def test_cancel_button_at_confirming(repo):
    drive_to(repo, "confirming")
    reply = send(repo, "Cancel")
    assert reply.text == "Okay, cancelled."
    assert state_of(repo) == "idle"


def test_cancel_booking_flow(repo):
    drive_to(repo, "managing_bookings")
    reply = send(repo, "1")
    assert reply.text == f"Cancel Haircut on {SLOT_LABEL}? (Yes / No)"
    assert state_of(repo) == "confirm_cancel"

    reply = send(repo, "Yes")
    assert reply.text == "Cancelled."
    assert state_of(repo) == "idle"
    assert repo.appointments[0]["status"] == "cancelled"
    assert repo.slots[repo.appointments[0]["slot_id"]]["is_booked"] is False


def test_confirm_cancel_no_keeps_booking(repo):
    drive_to(repo, "confirm_cancel")
    reply = send(repo, "No")
    assert reply.text == "Kept it."
    assert state_of(repo) == "idle"
    assert repo.appointments[0]["status"] == "confirmed"


def test_cancel_booking_twice_is_graceful(repo):
    drive_to(repo, "confirm_cancel")
    repo.appointments[0]["status"] = "cancelled"  # cancelled elsewhere
    reply = send(repo, "Yes")
    assert "already cancelled" in reply.text
    assert state_of(repo) == "idle"


def test_stale_booking_list_refreshes(repo):
    drive_to(repo, "managing_bookings")
    repo.appointments[0]["status"] = "cancelled"  # list is now stale
    reply = send(repo, "1")
    assert "no longer exists" in reply.text
    assert state_of(repo) == "idle"  # no bookings left -> back to idle


def test_menu_button_my_bookings(repo):
    drive_to(repo, "post_booking")
    send(repo, "No")
    reply = send(repo, "My bookings")
    assert "Your bookings" in reply.text
    assert state_of(repo) == "managing_bookings"


def test_unknown_state_row_treated_as_idle(repo):
    repo.set_state(USER, "some_legacy_state", {})
    reply = send(repo, "book")
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


# --- timezone selection ---------------------------------------------------------

def test_timezone_preset_selection_persists(repo):
    reply = send(repo, "/timezone")
    assert "Pick a timezone" in reply.text
    assert ["São Paulo", "Lisbon"] in reply.keyboard
    assert state_of(repo) == "choosing_timezone"

    reply = send(repo, "London")
    assert "Europe/London" in reply.text
    assert repo.user_timezones[USER] == "Europe/London"
    assert state_of(repo) == "idle"


def test_timezone_other_accepts_typed_iana_name(repo):
    send(repo, "/timezone")
    reply = send(repo, "Other")
    assert "IANA" in reply.text
    assert state_of(repo) == "typing_timezone"

    reply = send(repo, "Asia/Kolkata")
    assert "Asia/Kolkata" in reply.text
    assert repo.user_timezones[USER] == "Asia/Kolkata"
    assert state_of(repo) == "idle"


@pytest.mark.parametrize("bad_name", [
    "Mars/OlympusMons", "not a timezone", "12345", "",
])
def test_timezone_typed_invalid_reprompts(repo, bad_name):
    send(repo, "/timezone")
    send(repo, "Other")

    reply = send(repo, bad_name)

    assert "IANA name" in reply.text  # helpful: says what's expected
    assert USER not in repo.user_timezones  # nothing saved
    assert state_of(repo) == "typing_timezone"  # can just try again


def test_timezone_menu_unknown_pick_reprompts(repo):
    send(repo, "/timezone")
    reply = send(repo, "Tokyo")
    assert "pick one of the options" in reply.text.lower()
    assert USER not in repo.user_timezones
    assert state_of(repo) == "choosing_timezone"


def test_formatting_uses_saved_timezone_else_fallback(repo):
    # No setting saved: business-timezone fallback (America/Sao_Paulo, UTC-3).
    send(repo, "book")
    reply = send(repo, "1")
    assert f"1. {SLOT_LABEL}" in reply.text  # 17:00Z -> 14:00 (UTC-3)
    send(repo, "/cancel")

    # Saved timezone wins: 17:00Z -> 22:30 in Asia/Kolkata.
    send(repo, "/timezone")
    send(repo, "Other")
    send(repo, "Asia/Kolkata")
    send(repo, "book")
    reply = send(repo, "1")
    assert "1. Mon 27 Jul, 22:30 (IST)" in reply.text


def test_dst_sensitive_abbreviation_london(repo):
    haircut = next(s["id"] for s in repo.services if s["name"] == "Haircut")
    repo.add_slot(haircut, datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc))
    send(repo, "/timezone")
    send(repo, "London")

    send(repo, "book")
    reply = send(repo, "1")

    # July slot: UTC+1 with DST -> 18:00 (BST); January slot: UTC+0 -> (GMT).
    assert "Mon 27 Jul, 18:00 (BST)" in reply.text
    assert "Fri 15 Jan, 12:00 (GMT)" in reply.text


# --- admin: permission check --------------------------------------------------

ADMIN = 999
ADMIN_COMMANDS = ["/addslot", "/slots", "/appointments"]


def send_as(repo, user_id, text, admin_user_id=ADMIN):
    return handle_message(
        user_id, text, repo, user_name="Ana Silva", admin_user_id=admin_user_id
    )


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_non_admin_gets_idle_fallback_not_a_reveal(repo, command):
    reply = send_as(repo, USER, command)  # USER != ADMIN
    assert "didn't catch that" in reply.text
    assert "admin" not in reply.text.lower()
    assert state_of(repo) == "idle"


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_non_admin_mid_flow_gets_state_fallback(repo, command):
    drive_to(repo, "choosing_service")
    reply = send_as(repo, USER, command)
    assert "between 1 and 2" in reply.text  # choosing_service's own fallback
    assert "admin" not in reply.text.lower()
    assert state_of(repo) == "choosing_service"


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
def test_admin_commands_unconfigured(repo, command):
    reply = send_as(repo, USER, command, admin_user_id=None)
    assert "not configured" in reply.text


def test_admin_id_must_match_exactly(repo):
    reply = send_as(repo, ADMIN, "/addslot", admin_user_id=ADMIN)
    assert "Add a slot for which service?" in reply.text
    assert state_of(repo, ADMIN) == "admin_choosing_service"


# --- admin: /addslot flow and datetime validation ---------------------------

def drive_admin_to_datetime(repo):
    send_as(repo, ADMIN, "/addslot")
    reply = send_as(repo, ADMIN, "1")  # Haircut
    assert "2026-08-01 14:00" in reply.text  # format example shown
    assert state_of(repo, ADMIN) == "admin_typing_datetime"


def test_addslot_creates_future_slot(repo):
    drive_admin_to_datetime(repo)
    slots_before = len(repo.slots)

    reply = send_as(repo, ADMIN, "2030-08-01 14:00")

    # typed as Sao Paulo local time, echoed back the same way...
    assert "Added: Haircut — Thu 1 Aug, 14:00 (UTC-3)" in reply.text
    assert len(repo.slots) == slots_before + 1
    created = max(repo.slots.values(), key=lambda s: s["id"])
    # ...but stored in UTC (14:00-03:00 == 17:00Z)
    assert created["starts_at"] == datetime(2030, 8, 1, 17, 0, tzinfo=timezone.utc)
    assert created["is_booked"] is False
    # stays in the state so more slots can be added back to back
    assert state_of(repo, ADMIN) == "admin_typing_datetime"


@pytest.mark.parametrize("bad_datetime", [
    "tomorrow",
    "2030-08-01",        # date only
    "14:00",             # time only
    "2030-13-01 14:00",  # month 13
    "01-08-2030 14:00",  # wrong field order
    "2030-08-01 14:00:00",  # seconds not in format
])
def test_addslot_rejects_unparseable_datetime(repo, bad_datetime):
    drive_admin_to_datetime(repo)
    before = repo.get_state(ADMIN)
    slots_before = len(repo.slots)

    reply = send_as(repo, ADMIN, bad_datetime)

    assert "2026-08-01 14:00" in reply.text  # re-prompt repeats the format
    assert len(repo.slots) == slots_before  # nothing created
    assert repo.get_state(ADMIN) == before


def test_addslot_rejects_past_datetime(repo):
    drive_admin_to_datetime(repo)
    slots_before = len(repo.slots)

    reply = send_as(repo, ADMIN, "2020-01-01 10:00")

    assert "in the past" in reply.text
    assert len(repo.slots) == slots_before
    assert state_of(repo, ADMIN) == "admin_typing_datetime"


def test_cancel_exits_addslot_flow(repo):
    drive_admin_to_datetime(repo)
    reply = send_as(repo, ADMIN, "/cancel")
    assert reply.text == "Okay, cancelled."
    assert state_of(repo, ADMIN) == "idle"


# --- admin: /slots and /appointments -----------------------------------------

def test_admin_slots_shows_booked_and_free(repo):
    drive_to(repo, "post_booking")  # USER books the first Haircut slot
    reply = send_as(repo, ADMIN, "/slots")
    assert "Upcoming slots:" in reply.text
    assert f"{SLOT_LABEL} — Haircut — booked" in reply.text
    assert "— free" in reply.text  # the remaining slots
    assert state_of(repo, ADMIN) == "idle"


def test_admin_appointments_lists_all_users(repo):
    drive_to(repo, "post_booking")
    reply = send_as(repo, ADMIN, "/appointments")
    assert "Upcoming appointments:" in reply.text
    assert f"{SLOT_LABEL} — Haircut — Ana Silva" in reply.text
    assert state_of(repo, ADMIN) == "idle"


def test_admin_lists_when_empty(repo):
    repo.slots = {}
    assert send_as(repo, ADMIN, "/slots").text == "No upcoming slots."
    assert send_as(repo, ADMIN, "/appointments").text == "No upcoming appointments."
