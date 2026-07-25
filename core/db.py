# db.py: psycopg2 connection helper.
# Provides a single function to open a connection to the PostgreSQL database
# configured via DATABASE_URL. Callers are responsible for closing the
# connection (or using it as a context manager).

import psycopg2

from core.config import DATABASE_URL


def get_connection():
    """Open and return a new psycopg2 connection to the configured database."""
    return psycopg2.connect(DATABASE_URL)
