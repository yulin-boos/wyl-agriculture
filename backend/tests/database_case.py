import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.catalog import seed_database
from app.database import Base, get_session
from app.main import app


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_engine = create_engine(f"sqlite:///{Path(self.directory.name).as_posix()}/test.db", connect_args={"check_same_thread": False})
        self.addCleanup(self.db_engine.dispose)
        event.listen(self.db_engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.db_engine)
        self.sessions = sessionmaker(self.db_engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            seed_database(session)
        def get_test_session():
            with self.sessions() as session:
                yield session
        app.dependency_overrides[get_session] = get_test_session
        self.addCleanup(app.dependency_overrides.clear)
        patcher = patch("app.services.SessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"AUTH_SECRET_KEY": "test-only-secret-key-at-least-32-bytes", "ADMIN_API_TOKEN": "test-admin-token"})
        env.start()
        self.addCleanup(env.stop)
