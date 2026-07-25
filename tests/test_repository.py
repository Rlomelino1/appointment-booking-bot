# Integration tests for bots/appointment/repository.py against a real
# PostgreSQL database.
# They only run when TEST_DATABASE_URL points at a scratch database; otherwise
# the whole module is skipped. Every test starts from a freshly applied
# schema.sql and the tables are dropped again afterwards — NEVER point
# TEST_DATABASE_URL at a database whose contents you care about.

import os
from contextlib import closing
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set — skipping repository integration tests. "
        "Point it at a scratch PostgreSQL database to run them.",
        allow_module_level=True,
    )

# core.config reads the environment at import time and load_dotenv() does not
# override variables that are already set — so exporting these BEFORE the
# imports below routes all repository connections to the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("APPOINTMENT_BOT_TOKEN", "test-token")

import psycopg2  # noqa: E402

from bots.appointment import repository  # noqa: E402
from core import db  # noqa: E402

db.DATABASE_URL = TEST_DATABASE_URL  # belt and braces if core.config loaded earlier

USER = 111
SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "schema.sql").read_text()
DROP_SQL = (
    "DROP TABLE IF EXISTS "
    "appointments, conversation_state, user_settings, slots, services CASCADE"
)


def execute(sql, params=()):
    with closing(psycopg2.connect(TEST_DATABASE_URL)) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None


@pytest.fixture(autouse=True)
def clean_schema():
    execute(DROP_SQL)
    execute(SCHEMA_SQL)
    yield
    execute(DROP_SQL)


@pytest.fixture
def seeded():
    """One service with one bookable slot tomorrow; returns their ids."""
    [(service_id,)] = execute(
        "INSERT INTO services (name, duration_minutes) VALUES ('Haircut', 30) RETURNING id"
    )
    [(slot_id,)] = execute(
        "INSERT INTO slots (service_id, starts_at) VALUES (%s, now() + interval '1 day') RETURNING id",
        (service_id,),
    )
    return service_id, slot_id


def test_booking_marks_slot_unavailable(seeded):
    service_id, slot_id = seeded

    appointment = repository.book_slot(USER, slot_id, "Ana Silva")

    assert appointment["slot_id"] == slot_id
    assert appointment["status"] == "confirmed"
    assert appointment["customer_name"] == "Ana Silva"
    [(is_booked,)] = execute("SELECT is_booked FROM slots WHERE id = %s", (slot_id,))
    assert is_booked is True
    assert repository.list_available_slots(service_id) == []


def test_booking_same_slot_twice_second_fails_cleanly(seeded):
    _, slot_id = seeded

    repository.book_slot(USER, slot_id, "Ana Silva")
    with pytest.raises(repository.SlotAlreadyBookedError):
        repository.book_slot(222, slot_id, "Bruno Costa")

    # the failed attempt wrote nothing
    [(count,)] = execute("SELECT count(*) FROM appointments")
    assert count == 1
    [(owner,)] = execute(
        "SELECT telegram_user_id FROM appointments WHERE slot_id = %s", (slot_id,)
    )
    assert owner == USER


def test_cancelling_frees_slot(seeded):
    service_id, slot_id = seeded
    appointment = repository.book_slot(USER, slot_id, "Ana Silva")

    repository.cancel_appointment(appointment["id"], USER)

    [(status,)] = execute(
        "SELECT status FROM appointments WHERE id = %s", (appointment["id"],)
    )
    assert status == "cancelled"
    [(is_booked,)] = execute("SELECT is_booked FROM slots WHERE id = %s", (slot_id,))
    assert is_booked is False
    assert [s["id"] for s in repository.list_available_slots(service_id)] == [slot_id]

    # cancelling the same appointment again raises instead of double-freeing
    with pytest.raises(repository.AppointmentNotFoundError):
        repository.cancel_appointment(appointment["id"], USER)
