# repository.py: data-access layer — ALL SQL lives here.
# Other modules call functions from this file; they never write SQL themselves.
# Every query is parameterized (%s placeholders) — no string formatting in SQL.
# Each function opens its own short-lived connection; multi-statement writes
# (book_slot, cancel_appointment) run inside a single transaction.

from contextlib import closing

from psycopg2.extras import Json, RealDictCursor

from app.db import get_connection


class SlotAlreadyBookedError(Exception):
    """Raised when trying to book a slot that was already taken."""


class AppointmentNotFoundError(Exception):
    """Raised when cancelling an appointment that doesn't exist,
    belongs to another user, or is already cancelled."""


def _query(sql, params=()):
    """Run a single read-only query and return all rows as dicts."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


# --- conversation state -----------------------------------------------------

def get_state(telegram_user_id):
    """Return {'state': str, 'context': dict} for the user, or None."""
    rows = _query(
        "SELECT state, context FROM conversation_state WHERE telegram_user_id = %s",
        (telegram_user_id,),
    )
    return rows[0] if rows else None


def set_state(telegram_user_id, state, context=None):
    """Upsert the user's conversation state and context."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_state (telegram_user_id, state, context, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (telegram_user_id)
                DO UPDATE SET state = EXCLUDED.state,
                              context = EXCLUDED.context,
                              updated_at = now()
                """,
                (telegram_user_id, state, Json(context or {})),
            )


def clear_state(telegram_user_id):
    """Delete the user's conversation state (no-op if absent)."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversation_state WHERE telegram_user_id = %s",
                (telegram_user_id,),
            )


# --- user settings ----------------------------------------------------------

def get_user_timezone(telegram_user_id):
    """Return the user's saved IANA timezone name, or None."""
    rows = _query(
        "SELECT timezone FROM user_settings WHERE telegram_user_id = %s",
        (telegram_user_id,),
    )
    return rows[0]["timezone"] if rows else None


def set_user_timezone(telegram_user_id, timezone_name):
    """Upsert the user's display timezone (an IANA name, validated upstream)."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_settings (telegram_user_id, timezone)
                VALUES (%s, %s)
                ON CONFLICT (telegram_user_id)
                DO UPDATE SET timezone = EXCLUDED.timezone
                """,
                (telegram_user_id, timezone_name),
            )


# --- services & slots -------------------------------------------------------

def list_services():
    """Return all active services, ordered by name."""
    return _query(
        """
        SELECT id, name, duration_minutes
        FROM services
        WHERE active = true
        ORDER BY name
        """
    )


def list_available_slots(service_id):
    """Return future, unbooked slots for a service, soonest first."""
    return _query(
        """
        SELECT id, starts_at
        FROM slots
        WHERE service_id = %s
          AND is_booked = false
          AND starts_at > now()
        ORDER BY starts_at
        """,
        (service_id,),
    )


def create_slot(service_id, starts_at):
    """Insert a new bookable slot and return its id (admin /addslot)."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO slots (service_id, starts_at)
                VALUES (%s, %s)
                RETURNING id
                """,
                (service_id, starts_at),
            )
            return cur.fetchone()[0]


def list_upcoming_slots():
    """Return all future slots with service name and booked flag (admin /slots)."""
    return _query(
        """
        SELECT sl.id, sl.starts_at, sl.is_booked, s.name AS service_name
        FROM slots sl
        JOIN services s ON s.id = sl.service_id
        WHERE sl.starts_at > now()
        ORDER BY sl.starts_at
        """
    )


def list_upcoming_appointments():
    """Return all users' upcoming confirmed appointments (admin /appointments)."""
    return _query(
        """
        SELECT a.id, a.customer_name, s.name AS service_name, sl.starts_at
        FROM appointments a
        JOIN services s ON s.id = a.service_id
        JOIN slots sl ON sl.id = a.slot_id
        WHERE a.status = 'confirmed'
          AND sl.starts_at > now()
        ORDER BY sl.starts_at
        """
    )


# --- appointments -----------------------------------------------------------

def book_slot(telegram_user_id, slot_id, customer_name):
    """Book a slot atomically and return the new appointment as a dict.

    The slot is claimed with UPDATE ... WHERE is_booked = false RETURNING id:
    if another user already took it, no row comes back and we raise
    SlotAlreadyBookedError without inserting anything. Claim + insert share
    one transaction, so a failure at any point leaves the slot untouched.
    """
    with closing(get_connection()) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE slots
                SET is_booked = true
                WHERE id = %s
                  AND is_booked = false
                  AND starts_at > now()
                RETURNING id, service_id, starts_at
                """,
                (slot_id,),
            )
            slot = cur.fetchone()
            if slot is None:
                raise SlotAlreadyBookedError(
                    f"Slot {slot_id} is already booked or no longer available."
                )
            cur.execute(
                """
                INSERT INTO appointments
                    (telegram_user_id, service_id, slot_id, customer_name)
                VALUES (%s, %s, %s, %s)
                RETURNING id, telegram_user_id, service_id, slot_id,
                          customer_name, created_at, status
                """,
                (telegram_user_id, slot["service_id"], slot_id, customer_name),
            )
            appointment = cur.fetchone()
            appointment["starts_at"] = slot["starts_at"]
            return appointment


def list_appointments_for_user(telegram_user_id):
    """Return the user's confirmed upcoming appointments, soonest first."""
    return _query(
        """
        SELECT a.id, a.customer_name, a.status, a.created_at,
               s.name AS service_name, s.duration_minutes,
               sl.starts_at
        FROM appointments a
        JOIN services s ON s.id = a.service_id
        JOIN slots sl ON sl.id = a.slot_id
        WHERE a.telegram_user_id = %s
          AND a.status = 'confirmed'
          AND sl.starts_at > now()
        ORDER BY sl.starts_at
        """,
        (telegram_user_id,),
    )


def cancel_appointment(appointment_id, telegram_user_id):
    """Cancel the user's appointment and free its slot, atomically.

    The status flip and the slot release happen in one transaction, and the
    UPDATE only matches a still-confirmed appointment owned by this user —
    cancelling twice (or someone else's appointment) raises instead of
    silently double-freeing the slot.
    """
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE appointments
                SET status = 'cancelled'
                WHERE id = %s
                  AND telegram_user_id = %s
                  AND status = 'confirmed'
                RETURNING slot_id
                """,
                (appointment_id, telegram_user_id),
            )
            row = cur.fetchone()
            if row is None:
                raise AppointmentNotFoundError(
                    f"No confirmed appointment {appointment_id} for this user."
                )
            cur.execute(
                "UPDATE slots SET is_booked = false WHERE id = %s",
                (row[0],),
            )
