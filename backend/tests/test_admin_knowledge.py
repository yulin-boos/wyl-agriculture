import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from database_case import DatabaseTestCase
from app.main import app
from app.models import KnowledgeRecord, User
from app.services import DiagnosisWebService
from app.catalog import ROOT


class AdminKnowledgeTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.instance = DiagnosisWebService()
        self.item = json.loads((ROOT / "knowledge/disease_guidance.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.item["id"] = "KB-ADMIN-TEST-001"
        self.headers = {"Authorization": "Bearer test-admin-token"}
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        patcher = patch("app.admin.service", self.instance)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, item=None):
        return self.client.post("/api/admin/knowledge", json=self.item if item is None else item, headers=self.headers)

    def count(self):
        with self.sessions() as session:
            return session.scalar(select(func.count(KnowledgeRecord.id)))

    def test_admin_auth(self):
        before = self.count()
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            self.assertEqual(self.client.post("/api/admin/knowledge", json=self.item, headers=headers).status_code, 401)
            self.assertEqual(self.client.get("/api/admin/knowledge/labels", headers=headers).status_code, 401)
        self.assertEqual(before, self.count())

    def test_template_submit_persists_and_refreshes_other_worker(self):
        observer = DiagnosisWebService()
        observer.supports_crop(self.item["crop"])
        response = self.client.get("/api/admin/knowledge/template", params={"label": self.item["label"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["disease_zh"], self.item["disease_zh"])
        self.assertEqual(self.post(response.json()).status_code, 422)
        self.assertEqual(self.post().status_code, 201)
        observer.supports_crop(self.item["crop"])
        hits = observer.knowledge_base.retrieve_for_diagnosis(
            {"predictions": [{"label": self.item["label"], "crop": self.item["crop"]}]}, top_k=100)
        self.assertIn(self.item["id"], [hit.chunk.entry.id for hit in hits])

    def test_validation_and_duplicates(self):
        before = self.count()
        for changes in ({"label": "Unknown___Disease"}, {"crop": "Apple"}, {"content": " "},
                        {"source_url": "javascript:alert(1)"}, {"tags": [" "]}, {"title": " "},
                        {"id": "../bad"}, {"unexpected": "field"}, {"disease_zh": "错误名称"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post({**self.item, **changes}).status_code, 422)
                self.assertEqual(before, self.count())
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(before + 1, self.count())

    def test_failed_index_rolls_back(self):
        before = self.count()
        with patch("app.services.ChunkedKnowledgeBase", side_effect=ValueError("invalid index")):
            self.assertEqual(self.post().status_code, 422)
        self.assertEqual(before, self.count())

    def test_concurrent_duplicate_insert(self):
        before = self.count()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.post().status_code, range(2)))
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertEqual(before + 1, self.count())

    def test_database_admin_role_and_disabled_user(self):
        data = {"username": "admin_test", "password": "strong-password-123"}
        self.assertEqual(self.client.post("/api/auth/register", json=data).status_code, 201)
        token = self.client.post("/api/auth/login", json=data).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.client.get("/api/admin/knowledge/labels", headers=headers).status_code, 403)
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.username == data["username"]))
            user.role = "admin"
        self.assertEqual(self.client.get("/api/admin/knowledge/labels", headers=headers).status_code, 200)
        with self.sessions.begin() as session:
            user = session.scalar(select(User).where(User.username == data["username"]))
            user.status = "disabled"
        self.assertEqual(self.client.get("/api/admin/knowledge/labels", headers=headers).status_code, 401)
