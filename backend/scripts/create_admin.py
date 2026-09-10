"""Create an administrator without putting their password in shell history."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.auth import RegisterInput, hash_password
from app.database import SessionLocal, check_schema
from app.models import User

if __name__ == "__main__":
    check_schema()
    name = input("Administrator username: ").strip().lower()
    password = getpass.getpass("Password (at least 10 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    data = RegisterInput(username=name, password=password)
    with SessionLocal.begin() as session:
        if session.scalar(select(User.id).where(User.username == name)):
            raise SystemExit("Username exists; no account was changed.")
        session.add(User(username=name, password_hash=hash_password(data.password), role="admin", status="active"))
    print("Administrator created.")
