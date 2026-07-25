# fake_repository.py: in-memory stand-in for app/repository.py.
# Implements the same functions and exceptions so it can be injected into
# app.dialogue.handle_message in unit tests. Not simulated: the time filter
# (starts_at > now()) of the real queries — tests must seed future slots.

from copy import deepcopy


class SlotAlreadyBookedError(Exception):
    """Raised when trying to book a slot that was already taken."""


class AppointmentNotFoundError(Exception):
    """Raised when cancelling an appointment that doesn't exist,
    belongs to another user, or is already cancelled."""


class FakeRepository:
    SlotAlreadyBookedError = SlotAlreadyBookedError
    AppointmentNotFoundError = AppointmentNotFoundError

    def __init__(self):
        self.states = {}          # user_id -> {"state": str, "context": dict}
        self.services = []        # {"id", "name", "duration_minutes"}
        self.slots = {}           # slot_id -> {"id", "service_id", "starts_at", "is_booked"}
        self.appointments = []    # rows shaped like the appointments table
        self.user_timezones = {}  # user_id -> IANA name (user_settings table)
        self._next_id = 1

    # --- seeding helpers (test-only, no counterpart in the real module) -----

    def add_service(self, name, duration_minutes=30):
        service_id = self._take_id()
        self.services.append(
            {"id": service_id, "name": name, "duration_minutes": duration_minutes}
        )
        return service_id

    def add_slot(self, service_id, starts_at):
        return self.create_slot(service_id, starts_at)

    def _take_id(self):
        self._next_id += 1
        return self._next_id - 1

    # --- conversation state --------------------------------------------------

    def get_state(self, telegram_user_id):
        row = self.states.get(telegram_user_id)
        # Deep copy, like a fresh row from the database: mutating the returned
        # dict must not silently change stored state.
        return deepcopy(row) if row else None

    def set_state(self, telegram_user_id, state, context=None):
        self.states[telegram_user_id] = {
            "state": state,
            "context": deepcopy(context or {}),
        }

    def clear_state(self, telegram_user_id):
        self.states.pop(telegram_user_id, None)

    # --- user settings --------------------------------------------------------

    def get_user_timezone(self, telegram_user_id):
        return self.user_timezones.get(telegram_user_id)

    def set_user_timezone(self, telegram_user_id, timezone_name):
        self.user_timezones[telegram_user_id] = timezone_name

    # --- services & slots ----------------------------------------------------

    def list_services(self):
        return sorted(deepcopy(self.services), key=lambda s: s["name"])

    def list_available_slots(self, service_id):
        return sorted(
            (deepcopy(s) for s in self.slots.values()
             if s["service_id"] == service_id and not s["is_booked"]),
            key=lambda s: s["starts_at"],
        )

    def create_slot(self, service_id, starts_at):
        slot_id = self._take_id()
        self.slots[slot_id] = {
            "id": slot_id,
            "service_id": service_id,
            "starts_at": starts_at,
            "is_booked": False,
        }
        return slot_id

    def list_upcoming_slots(self):
        service_names = {s["id"]: s["name"] for s in self.services}
        return sorted(
            ({**deepcopy(s), "service_name": service_names[s["service_id"]]}
             for s in self.slots.values()),
            key=lambda s: s["starts_at"],
        )

    def list_upcoming_appointments(self):
        service_names = {s["id"]: s["name"] for s in self.services}
        return sorted(
            ({**deepcopy(a), "service_name": service_names[a["service_id"]]}
             for a in self.appointments if a["status"] == "confirmed"),
            key=lambda a: a["starts_at"],
        )

    # --- appointments ----------------------------------------------------------

    def book_slot(self, telegram_user_id, slot_id, customer_name):
        slot = self.slots.get(slot_id)
        if slot is None or slot["is_booked"]:
            raise SlotAlreadyBookedError(f"Slot {slot_id} is already booked.")
        slot["is_booked"] = True
        appointment = {
            "id": self._take_id(),
            "telegram_user_id": telegram_user_id,
            "service_id": slot["service_id"],
            "slot_id": slot_id,
            "customer_name": customer_name,
            "status": "confirmed",
            "starts_at": slot["starts_at"],
        }
        self.appointments.append(appointment)
        return deepcopy(appointment)

    def list_appointments_for_user(self, telegram_user_id):
        service_names = {s["id"]: s["name"] for s in self.services}
        return sorted(
            ({**deepcopy(a), "service_name": service_names[a["service_id"]]}
             for a in self.appointments
             if a["telegram_user_id"] == telegram_user_id
             and a["status"] == "confirmed"),
            key=lambda a: a["starts_at"],
        )

    def cancel_appointment(self, appointment_id, telegram_user_id):
        appointment = next(
            (a for a in self.appointments
             if a["id"] == appointment_id
             and a["telegram_user_id"] == telegram_user_id
             and a["status"] == "confirmed"),
            None,
        )
        if appointment is None:
            raise AppointmentNotFoundError(
                f"No confirmed appointment {appointment_id} for this user."
            )
        appointment["status"] = "cancelled"
        self.slots[appointment["slot_id"]]["is_booked"] = False
