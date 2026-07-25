# Tests for the dialogue state machine, using an in-memory fake repository.
# app.dialogue imports neither telebot nor psycopg2, so these run anywhere.

from datetime import datetime, timedelta

import pytest

from app.dialogue import handle_message

USER = 111
NOW = datetime(2026, 7, 24, 9, 0)


class FakeRepo:
    """In-memory stand-in for app.repository with the same surface."""

    class SlotAlreadyBookedError(Exception):
        pass

    class AppointmentNotFoundError(Exception):
        pass

    def __init__(self):
        self.states = {}
        self.services = [
            {"id": 10, "name": "Haircut", "duration_minutes": 30},
            {"id": 20, "name": "Massage", "duration_minutes": 60},
        ]
        # slot id -> row
        self.slots = {
            1: {"id": 1, "service_id": 10, "starts_at": NOW + timedelta(days=3, hours=5), "is_booked": False},
            2: {"id": 2, "service_id": 10, "starts_at": NOW + timedelta(days=4), "is_booked": False},
            3: {"id": 3, "service_id": 20, "starts_at": NOW + timedelta(days=5), "is_booked": False},
        }
        self.appointments = []
        self._next_appointment_id = 1

    # conversation state
    def get_state(self, user_id):
        return self.states.get(user_id)

    def set_state(self, user_id, state, context=None):
        self.states[user_id] = {"state": state, "context": context or {}}

    def clear_state(self, user_id):
        self.states.pop(user_id, None)

    # services & slots
    def list_services(self):
        return sorted(self.services, key=lambda s: s["name"])

    def list_available_slots(self, service_id):
        return sorted(
            (s for s in self.slots.values()
             if s["service_id"] == service_id and not s["is_booked"]),
            key=lambda s: s["starts_at"],
        )

    # appointments
    def book_slot(self, user_id, slot_id, customer_name):
        slot = self.slots.get(slot_id)
        if slot is None or slot["is_booked"]:
            raise self.SlotAlreadyBookedError()
        slot["is_booked"] = True
        appointment = {
            "id": self._next_appointment_id,
            "telegram_user_id": user_id,
            "service_id": slot["service_id"],
            "slot_id": slot_id,
            "customer_name": customer_name,
            "status": "confirmed",
            "starts_at": slot["starts_at"],
        }
        self._next_appointment_id += 1
        self.appointments.append(appointment)
        return appointment

    def list_appointments_for_user(self, user_id):
        service_names = {s["id"]: s["name"] for s in self.services}
        return sorted(
            ({**a, "service_name": service_names[a["service_id"]]}
             for a in self.appointments
             if a["telegram_user_id"] == user_id and a["status"] == "confirmed"),
            key=lambda a: a["starts_at"],
        )

    def cancel_appointment(self, appointment_id, user_id):
        appointment = next(
            (a for a in self.appointments
             if a["id"] == appointment_id
             and a["telegram_user_id"] == user_id
             and a["status"] == "confirmed"),
            None,
        )
        if appointment is None:
            raise self.AppointmentNotFoundError()
        appointment["status"] = "cancelled"
        self.slots[appointment["slot_id"]]["is_booked"] = False


@pytest.fixture
def repo():
    return FakeRepo()


def state_of(repo, user_id=USER):
    row = repo.get_state(user_id)
    return row["state"] if row else "idle"


def book_up_to_confirming(repo):
    handle_message(USER, "book", repo)          # -> choosing_service
    handle_message(USER, "1", repo)             # Haircut -> choosing_slot
    return handle_message(USER, "1", repo, user_name="Ana")  # -> confirming


# --- global commands ----------------------------------------------------------

def test_start_greets_and_resets(repo):
    repo.set_state(USER, "confirming", {"service_id": 10, "slot_id": 1})
    reply = handle_message(USER, "/start", repo)
    assert "book" in reply.text.lower()
    assert ["Book an appointment"] in reply.keyboard
    assert state_of(repo) == "idle"


def test_cancel_lands_in_idle_from_every_state(repo):
    for state, context in [
        ("choosing_service", {"service_options": [10]}),
        ("choosing_slot", {"service_id": 10, "slot_options": [1]}),
        ("confirming", {"service_id": 10, "slot_id": 1}),
        ("post_booking", {}),
        ("managing_bookings", {"appointment_options": [1]}),
        ("confirm_cancel", {"appointment_id": 1}),
    ]:
        repo.set_state(USER, state, context)
        reply = handle_message(USER, "/cancel", repo)
        assert reply.text == "Okay, cancelled."
        assert state_of(repo) == "idle"


# --- booking flow -------------------------------------------------------------

def test_happy_path_booking(repo):
    reply = handle_message(USER, "Book an appointment", repo)
    assert "1. Haircut (30 min)" in reply.text
    assert "2. Massage (60 min)" in reply.text
    assert reply.keyboard == [["1", "2"]]
    assert state_of(repo) == "choosing_service"

    reply = handle_message(USER, "1", repo)  # Haircut: slots 1 then 2
    assert "Mon 27 Jul, 14:00" in reply.text
    assert state_of(repo) == "choosing_slot"

    reply = handle_message(USER, "1", repo, user_name="Ana Silva")
    assert "Haircut" in reply.text
    assert "Mon 27 Jul, 14:00" in reply.text
    assert "Ana Silva" in reply.text
    assert reply.keyboard == [["Confirm"], ["Change slot"], ["Cancel"]]
    assert state_of(repo) == "confirming"

    reply = handle_message(USER, "Confirm", repo, user_name="Ana Silva")
    assert reply.text.startswith("✅ Booked! Haircut on Mon 27 Jul, 14:00 under Ana Silva.")
    assert reply.keyboard == [["Yes", "No"]]
    assert state_of(repo) == "post_booking"
    assert repo.slots[1]["is_booked"] is True

    reply = handle_message(USER, "No", repo)
    assert "See you soon" in reply.text
    assert reply.keyboard is None
    assert state_of(repo) == "idle"


def test_post_booking_yes_restarts_flow(repo):
    book_up_to_confirming(repo)
    handle_message(USER, "Confirm", repo, user_name="Ana")
    reply = handle_message(USER, "Yes", repo)
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


def test_change_slot_reoffers_slots(repo):
    book_up_to_confirming(repo)
    reply = handle_message(USER, "Change slot", repo)
    assert "Pick a time" in reply.text
    assert state_of(repo) == "choosing_slot"


def test_cancel_button_at_confirming(repo):
    book_up_to_confirming(repo)
    reply = handle_message(USER, "Cancel", repo)
    assert reply.text == "Okay, cancelled."
    assert state_of(repo) == "idle"


# --- races & emptiness --------------------------------------------------------

def test_slot_taken_race_at_confirm(repo):
    book_up_to_confirming(repo)
    repo.slots[1]["is_booked"] = True  # someone else grabs it
    reply = handle_message(USER, "Confirm", repo, user_name="Ana")
    assert "just taken" in reply.text
    assert "Pick a time" in reply.text
    assert state_of(repo) == "choosing_slot"
    # the re-offered list no longer contains the taken slot
    assert repo.get_state(USER)["context"]["slot_options"] == [2]
    assert not repo.appointments  # no partial writes


def test_slot_taken_race_at_summary(repo):
    handle_message(USER, "book", repo)
    handle_message(USER, "1", repo)
    repo.slots[1]["is_booked"] = True  # taken between display and pick
    reply = handle_message(USER, "1", repo, user_name="Ana")
    assert "just taken" in reply.text
    assert state_of(repo) == "choosing_slot"


def test_no_services(repo):
    repo.services = []
    reply = handle_message(USER, "book", repo)
    assert "no services" in reply.text.lower()
    assert state_of(repo) == "idle"


def test_no_slots_reshows_services(repo):
    for slot in repo.slots.values():
        slot["is_booked"] = True
    handle_message(USER, "book", repo)
    reply = handle_message(USER, "2", repo)  # Massage, all booked
    assert "No free slots" in reply.text
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


def test_slots_capped_at_ten(repo):
    for i in range(30, 45):
        repo.slots[i] = {
            "id": i, "service_id": 20,
            "starts_at": NOW + timedelta(days=10, hours=i), "is_booked": False,
        }
    handle_message(USER, "book", repo)
    reply = handle_message(USER, "2", repo)  # Massage
    assert len(repo.get_state(USER)["context"]["slot_options"]) == 10
    assert "11." not in reply.text


# --- fallbacks ----------------------------------------------------------------

def test_out_of_range_number_keeps_state(repo):
    handle_message(USER, "book", repo)
    before = repo.get_state(USER)["context"]
    reply = handle_message(USER, "99", repo)
    assert "between 1 and 2" in reply.text
    assert state_of(repo) == "choosing_service"
    assert repo.get_state(USER)["context"] == before


def test_gibberish_in_confirming_reprompts(repo):
    book_up_to_confirming(repo)
    reply = handle_message(USER, "what?", repo)
    assert "Confirm, Change slot, or Cancel" in reply.text
    assert state_of(repo) == "confirming"


def test_gibberish_in_post_booking_reprompts(repo):
    book_up_to_confirming(repo)
    handle_message(USER, "Confirm", repo, user_name="Ana")
    reply = handle_message(USER, "maybe", repo)
    assert "Yes / No" in reply.text
    assert state_of(repo) == "post_booking"


def test_brand_new_user_unknown_message(repo):
    reply = handle_message(USER, "hello there", repo)
    assert "didn't catch that" in reply.text
    assert ["Book an appointment"] in reply.keyboard
    assert state_of(repo) == "idle"


def test_unknown_state_row_treated_as_idle(repo):
    repo.set_state(USER, "some_legacy_state", {})
    reply = handle_message(USER, "book", repo)
    assert "Which service" in reply.text
    assert state_of(repo) == "choosing_service"


# --- managing bookings --------------------------------------------------------

def make_booking(repo):
    book_up_to_confirming(repo)
    handle_message(USER, "Confirm", repo, user_name="Ana")
    handle_message(USER, "No", repo)


def test_mybookings_empty(repo):
    reply = handle_message(USER, "/mybookings", repo)
    assert reply.text == "You have no bookings yet."
    assert state_of(repo) == "idle"


def test_cancel_booking_flow(repo):
    make_booking(repo)
    reply = handle_message(USER, "/mybookings", repo)
    assert "1. Haircut — Mon 27 Jul, 14:00" in reply.text
    assert state_of(repo) == "managing_bookings"

    reply = handle_message(USER, "1", repo)
    assert "Cancel Haircut on Mon 27 Jul, 14:00? (Yes / No)" == reply.text
    assert state_of(repo) == "confirm_cancel"

    reply = handle_message(USER, "Yes", repo)
    assert reply.text == "Cancelled."
    assert state_of(repo) == "idle"
    assert repo.slots[1]["is_booked"] is False  # slot freed


def test_confirm_cancel_no_keeps_booking(repo):
    make_booking(repo)
    handle_message(USER, "/mybookings", repo)
    handle_message(USER, "1", repo)
    reply = handle_message(USER, "No", repo)
    assert reply.text == "Kept it."
    assert state_of(repo) == "idle"
    assert repo.appointments[0]["status"] == "confirmed"


def test_cancel_booking_twice_is_graceful(repo):
    make_booking(repo)
    handle_message(USER, "/mybookings", repo)
    handle_message(USER, "1", repo)  # -> confirm_cancel
    repo.appointments[0]["status"] = "cancelled"  # cancelled elsewhere
    reply = handle_message(USER, "Yes", repo)
    assert "already cancelled" in reply.text
    assert state_of(repo) == "idle"


def test_menu_button_my_bookings(repo):
    make_booking(repo)
    reply = handle_message(USER, "My bookings", repo)
    assert "Your bookings" in reply.text
    assert state_of(repo) == "managing_bookings"
