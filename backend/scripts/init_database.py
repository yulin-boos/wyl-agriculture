"""Explicit development initialization, or seed an already-created database."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import create_tables, SessionLocal
from app.catalog import seed_database

if __name__ == "__main__":
    create_tables()
    with SessionLocal.begin() as session:
        seed_database(session)
    print("Database initialized; existing records preserved.")
