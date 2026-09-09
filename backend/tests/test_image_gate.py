import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from PIL import Image
from fastapi.testclient import TestClient
from crop_disease.image_gate import AgriculturalImageGate, GateSettings, ImageGateError, evaluate_scores
from app.services import DiagnosisWebService
from app.main import app, get_session, service


class ImageGateTests(unittest.TestCase):
    def setUp(self):
        self.settings = GateSettings(Path("missing-model"))

    def test_crop_passes(self):
        self.assertTrue(evaluate_scores(.31, .24, self.settings)["accepted"])

    def test_non_crop_rejected(self):
        with self.assertRaises(ImageGateError) as caught:
            evaluate_scores(.20, .35, self.settings)
        self.assertEqual(caught.exception.code, "non_agricultural_image")

    def test_ambiguous_and_low_similarity_rejected(self):
        for positive, negative in ((.31, .30), (.19, .05)):
            with self.subTest(positive=positive), self.assertRaises(ImageGateError):
                evaluate_scores(positive, negative, self.settings)

    def test_invalid_scores_fail_closed(self):
        for score in (float("nan"), float("inf"), 2):
            with self.subTest(score=score), self.assertRaises(ImageGateError) as caught:
                evaluate_scores(score, .2, self.settings)
            self.assertEqual(caught.exception.status_code, 503)

    def test_invalid_threshold_rejected(self):
        with patch.dict(os.environ, {"IMAGE_GATE_MIN_MARGIN": "nan"}):
            with self.assertRaises(ValueError):
                GateSettings.from_env(Path("."))

    def test_corrupt_image_rejected_before_model(self):
        gate = AgriculturalImageGate(self.settings)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.jpg"
            path.write_bytes(b"not an image")
            with patch.object(gate, "_load") as load, self.assertRaises(ImageGateError) as caught:
                gate.check(path)
            load.assert_not_called()
        self.assertEqual(caught.exception.code, "invalid_image")

    def test_unavailable_model_rejects_valid_image(self):
        gate = AgriculturalImageGate(self.settings)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            Image.new("RGB", (32, 32)).save(path)
            with patch.object(gate, "_load", side_effect=OSError("missing")), self.assertRaises(ImageGateError) as caught:
                gate.check(path)
        self.assertEqual(caught.exception.status_code, 503)

    def test_rejection_never_runs_disease_model_or_advice(self):
        instance = DiagnosisWebService()
        instance.image_gate = Mock()
        instance.image_gate.check.side_effect = ImageGateError("non_agricultural_image", "拒绝")
        instance._engine = Mock()
        instance.advice_client = Mock()
        with self.assertRaises(ImageGateError):
            instance.diagnose(Path("anything.jpg"), "Tomato", {})
        instance._engine.predict.assert_not_called()
        instance.advice_client.generate.assert_not_called()

    def test_accepted_gate_preserves_diagnosis_flow(self):
        instance = DiagnosisWebService()
        instance.image_gate = Mock()
        instance.image_gate.check.return_value = {"accepted": True}
        instance._engine = Mock()
        instance._engine.predict.return_value = {"predictions": []}
        instance.knowledge_base = Mock()
        instance.knowledge_base.retrieve_for_diagnosis.return_value = [Mock()]
        instance.advice_client = Mock()
        instance.advice_client.generate.return_value = {}
        with patch("app.services.format_advice", return_value="report"):
            diagnosis, _, report = instance.diagnose(Path("crop.jpg"), "Tomato", {}, api_key="test")
        instance._engine.predict.assert_called_once()
        instance.advice_client.generate.assert_called_once()
        self.assertEqual(diagnosis["image_validation"], {"accepted": True})
        self.assertEqual(report, "report")

    def test_api_rejects_without_persistence_and_cleans_upload(self):
        session = Mock()
        app.dependency_overrides[get_session] = lambda: session
        seen = []
        def reject(path, *args):
            seen.append(path)
            raise ImageGateError("non_agricultural_image", "请上传农作物图片。")
        data = {"client_id": "12345678-1234-1234-1234-123456789012", "crop": "Tomato"}
        try:
            # No lifespan context: do not create tables or connect to a database.
            with patch.object(service, "diagnose", side_effect=reject):
                response = TestClient(app).post("/api/diagnoses", data=data,
                    files={"image": ("photo.jpg", b"test", "image/jpeg")})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["code"], "non_agricultural_image")
            self.assertIsInstance(response.json()["detail"], str)
            session.add.assert_not_called()
            session.commit.assert_not_called()
            self.assertTrue(seen)
            self.assertFalse(seen[0].exists())
        finally:
            app.dependency_overrides.clear()

    def test_api_model_failure_is_503(self):
        app.dependency_overrides[get_session] = lambda: Mock()
        try:
            with patch.object(service, "diagnose", side_effect=ImageGateError("image_gate_unavailable", "暂不可用", 503)):
                response = TestClient(app).post("/api/diagnoses", data={
                    "client_id": "12345678-1234-1234-1234-123456789012", "crop": "Tomato"},
                    files={"image": ("photo.jpg", b"test", "image/jpeg")})
            self.assertEqual(response.status_code, 503)
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
