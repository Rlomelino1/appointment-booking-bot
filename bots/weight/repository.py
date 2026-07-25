# repository.py: the weight bot's data-access layer — ALL its SQL lives here.
# Same rules as the appointment bot's repository: parameterized queries only,
# short-lived connections, one transaction per write.
# Conversation state uses weight_conversation_state — same shape as
# conversation_state, but per bot, so a user talking to both bots never has
# one bot's state overwrite the other's.

from contextlib import closing

from psycopg2.extras import Json, RealDictCursor

from core.db import get_connection, query


# --- conversation state -----------------------------------------------------

def get_state(telegram_user_id):
    """Return {'state': str, 'context': dict} for the user, or None."""
    rows = query(
        "SELECT state, context FROM weight_conversation_state "
        "WHERE telegram_user_id = %s",
        (telegram_user_id,),
    )
    return rows[0] if rows else None


def set_state(telegram_user_id, state, context=None):
    """Upsert the user's conversation state and context."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO weight_conversation_state
                    (telegram_user_id, state, context, updated_at)
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
                "DELETE FROM weight_conversation_state WHERE telegram_user_id = %s",
                (telegram_user_id,),
            )


# --- subscribers --------------------------------------------------------------

def get_subscriber(telegram_user_id):
    """Return the subscriber row, or None if the user never subscribed."""
    rows = query(
        """
        SELECT telegram_user_id, subscribed_at, active
        FROM weight_subscribers
        WHERE telegram_user_id = %s
        """,
        (telegram_user_id,),
    )
    return rows[0] if rows else None


def set_subscriber(telegram_user_id, active):
    """Upsert the subscription flag; subscribed_at is kept on reactivation."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO weight_subscribers (telegram_user_id, active)
                VALUES (%s, %s)
                ON CONFLICT (telegram_user_id)
                DO UPDATE SET active = EXCLUDED.active
                """,
                (telegram_user_id, active),
            )


def list_active_subscribers():
    """Return the user ids of all active subscribers."""
    rows = query(
        "SELECT telegram_user_id FROM weight_subscribers "
        "WHERE active = true ORDER BY telegram_user_id"
    )
    return [r["telegram_user_id"] for r in rows]


# --- weigh-ins ------------------------------------------------------------------

def add_weigh_in(telegram_user_id, weight_kg):
    """Insert a weigh-in (logged_at defaults to now()) and return the row."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO weigh_ins (telegram_user_id, weight_kg)
                VALUES (%s, %s)
                RETURNING id, telegram_user_id, weight_kg, logged_at
                """,
                (telegram_user_id, weight_kg),
            )
            return cur.fetchone()


def last_weigh_in(telegram_user_id):
    """Return the user's most recent weigh-in, or None."""
    rows = recent_weigh_ins(telegram_user_id, limit=1)
    return rows[0] if rows else None


def recent_weigh_ins(telegram_user_id, limit=8):
    """Return the user's most recent weigh-ins, newest first."""
    return query(
        """
        SELECT id, telegram_user_id, weight_kg, logged_at
        FROM weigh_ins
        WHERE telegram_user_id = %s
        ORDER BY logged_at DESC, id DESC
        LIMIT %s
        """,
        (telegram_user_id, limit),
    )
