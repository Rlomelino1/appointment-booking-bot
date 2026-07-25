# db.py: psycopg2 connection helpers shared by every bot's repository.
# get_connection opens a connection to the PostgreSQL database configured via
# DATABASE_URL; callers are responsible for closing it (or using it as a
# context manager). query runs a single read-only statement and returns rows
# as dicts.

from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor

from core.config import DATABASE_URL


def get_connection():
    """Open and return a new psycopg2 connection to the configured database."""
    return psycopg2.connect(DATABASE_URL)


def query(sql, params=()):
    """Run a single read-only query and return all rows as dicts."""
    with closing(get_connection()) as conn:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
