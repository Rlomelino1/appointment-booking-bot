# Unit tests for the dialogue state machine (app/dialogue.py).
# Everything runs against tests/fake_repository.FakeRepository — no database,
# no Telegram. States are reached by driving real messages through
# handle_message, so these tests exercise the same paths users do.

from datetime import datetime, timedelta

import pytest

from app.dialogue import handle_message
from tests.fake_repository import FakeRepository

USER = 111
NOW = datetime(2026, 7, 24, 9, 0)  # a Friday
SLOT_LABEL = "Mon 27 Jul, 14:00"


@pytest.fixture
def repo():
    r = FakeRepository()
    haircut = r.add_service("Haircut", 30)
    massage = r.add_service("Massage", 60)
    r.add_slot(haircut, NOW + timedelta(days=3, hours=5))  # Mon 27 Jul, 14:00
    r.add_slot(haircut, NOW + timedelta(days=4))
    r.add_slot(massage, NOW + timedelta(days=5))
    return r


def send(repo, text):
    return handle_message(USER, text, repo, user_name="Ana Silva")


def state_of(repo):
    row = repo.get_state(USER)
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
