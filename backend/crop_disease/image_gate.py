"""Local image-domain gate. Scores are similarities, not calibrated probabilities."""
from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


POSITIVE_PROMPTS = (
    "a photo of a crop plant leaf with plant disease spots",
    "a close up photo of a healthy agricultural crop leaf",
    "a photo of a tomato plant with tomatoes and leaves",
    "a photo of potato plants and their leaves",
    "a photo of corn plants and corn leaves",
    "a photo of fresh vegetables harvested from a farm",
    "a photo of fresh fruit harvested from an orchard",
    "a photo of harvested potatoes and root vegetables",
    "a photo of ears of corn and harvested cereal grains",
    "a photo of agricultural crop plants growing in a field",
)
NEGATIVE_PROMPTS = (
    "a photo of a person, a face or a selfie",
    "a photo of a hand or human skin",
    "a photo of a cat, dog or other animal",
    "a photo of a car, bicycle or other vehicle",
    "a photo of a phone, computer or electronic device",
    "a screenshot of an app, website or computer screen",
    "a photo of a document, text, book or QR code",
    "a photo of furniture or household objects in a room",
    "a photo of clothing, shoes or a bag",
    "a photo of buildings, roads or a city street",
    "a photo of a cooked meal or processed packaged food",
    "a drawing, cartoon, illustration or logo",
    "a photo of rocks, bare soil, water or sky without crops",
    "a blank, blurry, dark or unrecognizable image",
)


class ImageGateError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@dataclass(frozen=True)
class GateSettings:
    model_path: Path
    min_similarity: float = 0.22
    min_margin: float = 0.02

    @classmethod
    def from_env(cls, root: Path) -> "GateSettings":
        path = Path(os.getenv("IMAGE_GATE_MODEL_PATH", "models/image_gate").strip())
        similarity = float(os.getenv("IMAGE_GATE_MIN_SIMILARITY", "0.22"))
        margin = float(os.getenv("IMAGE_GATE_MIN_MARGIN", "0.02"))
        if not math.isfinite(similarity) or not 0 < similarity < 1:
            raise ValueError("IMAGE_GATE_MIN_SIMILARITY must be between 0 and 1")
        if not math.isfinite(margin) or not 0 < margin < 1:
            raise ValueError("IMAGE_GATE_MIN_MARGIN must be between 0 and 1")
        return cls(path if path.is_absolute() else root / path, similarity, margin)


def evaluate_scores(positive: float, negative: float, settings: GateSettings) -> dict:
    if not all(math.isfinite(v) and -1 <= v <= 1 for v in (positive, negative)):
        raise ImageGateError("image_gate_unavailable", "图片内容校验暂不可用，请稍后重试。", 503)
    if positive < settings.min_similarity or positive - negative < settings.min_margin:
        raise ImageGateError(
            "non_agricultural_image" if negative > positive else "uncertain_agricultural_image",
            "图片不是农作物或农产品，或无法确认其内容，已停止诊断。请上传清晰的作物、叶片或果蔬照片。",
        )
    return {
        "accepted": True,
        "method": "clip_domain_gate_v1",
        "agricultural_similarity": positive,
        "other_similarity": negative,
        "margin": positive - negative,
        "min_similarity": settings.min_similarity,
        "min_margin": settings.min_margin,
    }


class AgriculturalImageGate:
    def __init__(self, settings: GateSettings):
        self.settings = settings
        self._lock = threading.Lock()
        self._model = None
        self._processor = None
        self._text_features = None

    def _load(self) -> None:
        if self._model is not None:
            return
        # Never download weights in a user request or silently skip this gate.
        from transformers import CLIPModel, CLIPProcessor
        import torch

        path = str(self.settings.model_path)
        processor = CLIPProcessor.from_pretrained(path, local_files_only=True, use_fast=False)
        model = CLIPModel.from_pretrained(path, local_files_only=True, use_safetensors=True).eval()
        tokens = processor(text=list(POSITIVE_PROMPTS + NEGATIVE_PROMPTS), return_tensors="pt", padding=True)
        with torch.inference_mode():
            features = model.get_text_features(**tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        self._processor, self._text_features, self._model = processor, features, model

    def check(self, image_path: Path) -> dict:
        try:
            with Image.open(image_path) as source:
                if source.width * source.height > 25_000_000:
                    raise ImageGateError("invalid_image", "图片分辨率过大，请缩小后重试。")
                source.load()
                picture = ImageOps.exif_transpose(source).convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            raise ImageGateError("invalid_image", "无法读取图片，请上传有效的图片文件。") from error
        try:
            import torch

            with self._lock, torch.inference_mode():
                self._load()
                inputs = self._processor(images=picture, return_tensors="pt")
                features = self._model.get_image_features(**inputs)
                features = features / features.norm(dim=-1, keepdim=True)
                scores = (features @ self._text_features.T)[0]
                positive = float(scores[:len(POSITIVE_PROMPTS)].max())
                negative = float(scores[len(POSITIVE_PROMPTS):].max())
        except Exception as error:
            raise ImageGateError("image_gate_unavailable", "图片内容校验暂不可用，请稍后重试。", 503) from error
        finally:
            picture.close()
        return evaluate_scores(positive, negative, self.settings)
