# init_db.py: applies schema.sql and seed.sql to the database at DATABASE_URL.
# Run from the project root: python scripts/init_db.py
# Safe to re-run: the schema uses IF NOT EXISTS and the seed is idempotent.

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # allow package imports when run as a script

from contextlib import closing

from core.db import get_connection


def main() -> None:
    for sql_file in ("schema.sql", "seed.sql"):
        sql = (PROJECT_ROOT / sql_file).read_text(encoding="utf-8")
        with closing(get_connection()) as conn:
            with conn, conn.cursor() as cur:
                cur.execute(sql)
        print(f"Applied {sql_file}")
    print("Database initialized.")


if __name__ == "__main__":
    main()
