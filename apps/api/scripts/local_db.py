"""Docker-free local PostgreSQL 16 + pgvector via the `pgserver` dev dependency.

Usage (from apps/api):
    uv run python scripts/local_db.py            # start (or reuse) and print DATABASE_URL
    uv run python scripts/local_db.py --stop     # stop the server

Data lives in <repo>/data/pgdata (git-ignored). The server keeps running after this script exits.
Prefer `docker compose up -d db` when Docker is available.
"""

import argparse
import re
import sys
from pathlib import Path

PGDATA = Path(__file__).resolve().parents[3] / "data" / "pgdata"
DB_NAME = "tokenguard"


def start(db_name: str = DB_NAME) -> str:
    import pgserver

    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", db_name):
        raise SystemExit("database name must be a simple lowercase identifier")

    srv = pgserver.get_server(PGDATA, cleanup_mode=None)
    exists = srv.psql(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';")  # noqa: S608 - validated
    if "(1 row)" not in exists:
        srv.psql(f"CREATE DATABASE {db_name};")
    base = srv.get_uri().rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1)
    return f"{base}/{db_name}"


def stop() -> None:
    import pgserver

    pgserver.get_server(PGDATA, cleanup_mode="stop").cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--db", default=DB_NAME)
    args = parser.parse_args()
    if args.stop:
        stop()
        print("stopped")
        sys.exit(0)
    print(start(args.db))
