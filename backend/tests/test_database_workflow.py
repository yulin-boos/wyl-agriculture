import uuid
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from database_case import DatabaseTestCase
from app.main import app, service
from app.database import Base
from app.models import Crop, Disease, DiagnosisFeedback, DiagnosisRecord, KnowledgeRecord, User
from app.catalog import seed_database
from scripts.export_mysql_schema import build_sql


class DatabaseWorkflowTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.client_id = str(uuid.uuid4())
        self.data = {"client_id": self.client_id, "crop": "Tomato"}
        self.diagnosis = {"predictions": [{"label": "Tomato___Bacterial_spot", "crop": "Tomato", "crop_zh": "番茄", "disease_zh": "细菌性斑点病", "confidence": .95}], "decision": "needs_review"}
        self.advice = {"likelihood_percent": 95, "knowledge_sources": []}

    def diagnose(self, headers=None, data=None):
        with patch.object(service, "diagnose", return_value=(self.diagnosis, self.advice, "报告")):
            return self.client.post("/api/diagnoses", data=self.data if data is None else data,
                                    files={"image": ("leaf.jpg", b"fake-image-for-mocked-inference", "image/jpeg")}, headers=headers or {})

    def login(self, name="user_test"):
        data = {"username": name, "password": "test-password-1234"}
        response = self.client.post("/api/auth/register", json=data)
        self.assertEqual(response.status_code, 201)
        response = self.client.post("/api/auth/login", json=data)
        self.assertEqual(response.status_code, 200)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_guest_diagnosis_history_feedback_and_cascade(self):
        response = self.diagnose()
        self.assertEqual(response.status_code, 201, response.text)
        record_id = response.json()["id"]
        params = {"client_id": self.client_id}
        history = self.client.get("/api/diagnoses", params=params).json()
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["id"], record_id)
        with self.sessions() as session:
            record = session.get(DiagnosisRecord, record_id)
            disease = session.get(Disease, record.disease_id)
            self.assertEqual(record.crop_id, disease.crop_id)
            corrected = session.scalar(select(Disease).where(Disease.crop_id == disease.crop_id, Disease.id != disease.id))
            corrected_id = corrected.id
        endpoint = f"/api/diagnoses/{record_id}/feedback"
        feedback = {"is_correct": False, "corrected_disease_id": corrected_id, "content": "人工复核"}
        self.assertEqual(self.client.post(endpoint, params=params, json=feedback).status_code, 201)
        self.assertEqual(self.client.post(endpoint, params=params, json=feedback).status_code, 409)
        self.assertEqual(self.client.get(endpoint, params=params).json()["corrected_disease_id"], corrected_id)
        self.assertEqual(self.client.delete(f"/api/diagnoses/{record_id}", params=params).status_code, 204)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(DiagnosisFeedback.id))), 0)

    def test_user_records_cannot_be_accessed_by_client_id_or_other_user(self):
        headers = self.login()
        response = self.diagnose(headers=headers)
        self.assertEqual(response.status_code, 201)
        record_id = response.json()["id"]
        endpoint = f"/api/diagnoses/{record_id}"
        self.assertEqual(self.client.get(endpoint, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(endpoint, params={"client_id": self.client_id}).status_code, 404)
        other = self.login("other_user")
        self.assertEqual(self.client.delete(endpoint, headers=other).status_code, 404)
        self.assertEqual(self.client.post(endpoint + "/feedback", headers=other, json={"is_correct": True}).status_code, 404)
        self.assertEqual(self.diagnose(headers=headers, data={"crop": "Tomato"}).status_code, 201)

    def test_invalid_owner_and_cross_crop_feedback(self):
        self.assertEqual(self.diagnose(data={"crop": "Tomato"}).status_code, 422)
        self.assertEqual(self.client.get("/api/diagnoses").status_code, 422)
        response = self.diagnose()
        with self.sessions() as session:
            disease = session.scalar(select(Disease).where(Disease.model_label.like("Apple___%")))
            wrong_id = disease.id
        endpoint = f"/api/diagnoses/{response.json()['id']}/feedback"
        self.assertEqual(self.client.post(endpoint, params={"client_id": self.client_id},
                                         json={"is_correct": False, "corrected_disease_id": wrong_id}).status_code, 422)

    def test_accounts_hash_password_and_reject_escalation_and_expired_tokens(self):
        headers = self.login()
        self.assertNotIn("password", self.client.get("/api/auth/me", headers=headers).text)
        with self.sessions() as session:
            user = session.scalar(select(User).where(User.username == "user_test"))
            self.assertTrue(user.password_hash.startswith("pbkdf2_sha256$"))
            self.assertNotIn("test-password", user.password_hash)
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "bad_admin", "password": "password-12345", "role": "admin"}).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "user_test", "password": "wrong"}).status_code, 401)
        with patch("app.auth.time.time", return_value=9999999999):
            self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_schema_relationships_constraints_and_seed_idempotence(self):
        self.assertEqual(set(Base.metadata.tables), {"users", "crops", "diseases", "knowledge_base", "diagnosis_history", "diagnosis_feedback"})
        self.assertEqual(sum(len(t.foreign_keys) for t in Base.metadata.tables.values()), 8)
        with self.sessions.begin() as session:
            before = session.scalar(select(func.count(KnowledgeRecord.id)))
            seed_database(session)
            self.assertEqual(session.scalar(select(func.count(KnowledgeRecord.id))), before)
            self.assertEqual(session.scalar(select(func.count(Disease.id))), 38)
        with self.sessions() as session:
            with self.assertRaises(IntegrityError):
                session.execute(delete(Crop))
                session.commit()
            session.rollback()
        sql = build_sql()
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 6)
        self.assertEqual(sql.count("FOREIGN KEY"), 8)
        self.assertIn("ON DELETE CASCADE", sql)
        self.assertIn("ck_history_owner", sql)
        self.assertNotIn("DROP TABLE", sql)

    def test_database_owner_check(self):
        response = self.diagnose()
        with self.sessions() as session:
            record = session.get(DiagnosisRecord, response.json()["id"])
            record.client_id = None
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

    def test_database_storage_failure_does_not_claim_success(self):
        from sqlalchemy.exc import OperationalError
        from sqlalchemy.orm import Session
        with patch.object(Session, "commit", side_effect=OperationalError("insert", {}, RuntimeError("offline"))):
            response = self.diagnose()
        self.assertEqual(response.status_code, 503)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(DiagnosisRecord.id))), 0)

    def test_legacy_migration_preserves_ids_and_is_repeatable(self):
        from scripts.migrate_legacy_history import migrate
        response = self.diagnose()
        record_id = response.json()["id"]
        legacy_columns = [column.name for column in DiagnosisRecord.__table__.columns
                          if column.name not in {"user_id", "crop_id", "disease_id"}]
        with self.db_engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE diagnosis_records AS SELECT " + ", ".join(legacy_columns) + " FROM diagnosis_history")
            connection.execute(delete(DiagnosisRecord))
        with patch("scripts.migrate_legacy_history.SessionLocal", self.sessions), patch("app.database.engine", self.db_engine):
            self.assertEqual(migrate(self.db_engine), 1)
            self.assertEqual(migrate(self.db_engine), 0)
        with self.sessions() as session:
            migrated = session.get(DiagnosisRecord, record_id)
            self.assertEqual(migrated.advice_json, self.advice)
            self.assertEqual(migrated.client_id, self.client_id)
        with self.db_engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT count(*) FROM diagnosis_records").scalar(), 1)
