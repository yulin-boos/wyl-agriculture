from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Sequence

import torch
import yaml

from crop_disease.inference import allowed_indices_for_crop, constrain_probabilities
from crop_disease.quality import QualitySettings, assess_image


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

CROP_NAMES_ZH = {
    "Apple": "苹果",
    "Blueberry": "蓝莓",
    "Cherry_(including_sour)": "樱桃",
    "Corn_(maize)": "玉米",
    "Grape": "葡萄",
    "Orange": "柑橘",
    "Peach": "桃",
    "Pepper,_bell": "甜椒",
    "Potato": "马铃薯",
    "Raspberry": "树莓",
    "Soybean": "大豆",
    "Squash": "南瓜",
    "Strawberry": "草莓",
    "Tomato": "番茄",
}

DISEASE_NAMES_ZH = {
    "Apple_scab": "苹果黑星病",
    "Black_rot": "黑腐病",
    "Cedar_apple_rust": "雪松苹果锈病",
    "Powdery_mildew": "白粉病",
    "Cercospora_leaf_spot Gray_leaf_spot": "灰斑病",
    "Common_rust_": "普通锈病",
    "Northern_Leaf_Blight": "北方叶枯病",
    "Esca_(Black_Measles)": "黑麻疹病",
    "Leaf_blight_(Isariopsis_Leaf_Spot)": "叶枯病",
    "Haunglongbing_(Citrus_greening)": "黄龙病",
    "Bacterial_spot": "细菌性斑点病",
    "Early_blight": "早疫病",
    "Late_blight": "晚疫病",
    "Leaf_scorch": "叶焦病",
    "Leaf_Mold": "叶霉病",
    "Septoria_leaf_spot": "斑枯病",
    "Spider_mites Two-spotted_spider_mite": "二斑叶螨",
    "Target_Spot": "靶斑病",
    "Tomato_Yellow_Leaf_Curl_Virus": "黄化曲叶病毒病",
    "Tomato_mosaic_virus": "花叶病毒病",
    "healthy": "健康",
}

DECISION_REASON_NAMES_ZH = {
    "crop_confirmation_required": "需要先确认作物类型",
    "crop_mismatch_or_unknown": "所选作物与图像不匹配，或图片可能超出模型识别范围",
    "low_confidence": "模型置信度不足",
    "image_quality_failed": "图片质量不符合识别要求",
    "confidence_threshold_met": "置信度达到安全阈值",
}


@dataclass(frozen=True)
class InferenceSettings:
    model_path: Path
    labels_path: Path
    image_size: int
    top_k: int
    require_crop_confirmation: bool
    unconstrained_rejection_threshold: float
    crop_constrained_rejection_threshold: float
    low_confidence_action: str
    minimum_crop_probability_mass: float = 0.05
    quality: QualitySettings = QualitySettings()

    @classmethod
    def from_yaml(cls, path: Path, project_root: Path | None = None) -> "InferenceSettings":
        path = path.resolve()
        root = project_root.resolve() if project_root else path.parent.parent
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(value: str) -> Path:
            candidate = Path(value)
            return candidate if candidate.is_absolute() else root / candidate

        return cls(
            model_path=resolve(str(payload["model"])),
            labels_path=resolve(str(payload["labels"])),
            image_size=int(payload["image_size"]),
            top_k=int(payload["top_k"]),
            require_crop_confirmation=bool(payload["require_crop_confirmation"]),
            unconstrained_rejection_threshold=float(
                payload["unconstrained_rejection_threshold"]
            ),
            crop_constrained_rejection_threshold=float(
                payload["crop_constrained_rejection_threshold"]
            ),
            low_confidence_action=str(payload["low_confidence_action"]),
            minimum_crop_probability_mass=float(
                payload.get("minimum_crop_probability_mass", 0.05)
            ),
            quality=QualitySettings.from_mapping(payload.get("quality")),
        )

    def labels(self) -> list[str]:
        payload = json.loads(self.labels_path.read_text(encoding="utf-8"))
        return [
            label
            for label, _ in sorted(
                payload["label_to_id"].items(), key=lambda item: int(item[1])
            )
        ]


def available_crops(labels: Sequence[str]) -> list[str]:
    return sorted({label.partition("___")[0] for label in labels})


def display_crop(crop: str) -> str:
    return CROP_NAMES_ZH.get(crop, crop.replace("_", " "))


def display_disease(disease: str) -> str:
    return DISEASE_NAMES_ZH.get(disease, disease.replace("_", " "))


def display_label(label: str) -> str:
    crop, _, disease = label.partition("___")
    return f"{display_crop(crop)} - {display_disease(disease)}"


def interpret_probabilities(
    probabilities: torch.Tensor,
    labels: list[str],
    settings: InferenceSettings,
    crop: str | None = None,
    top_k: int | None = None,
    rejection_threshold: float | None = None,
    allowed_labels: Collection[str] | None = None,
) -> dict[str, object]:
    probabilities = probabilities.detach().cpu()
    if probabilities.ndim != 1 or len(probabilities) != len(labels):
        raise ValueError("Probability vector does not match the model taxonomy.")

    raw_index = int(probabilities.argmax())
    raw_confidence = float(probabilities[raw_index])
    if crop:
        crop_allowed = allowed_indices_for_crop(labels, crop)
        crop_probability_mass = float(probabilities[crop_allowed].sum())
        interpreted = constrain_probabilities(probabilities, crop_allowed)
        default_threshold = settings.crop_constrained_rejection_threshold
        threshold_source = "crop_constrained_validation"
        eligible_indices = crop_allowed
    else:
        crop_probability_mass = None
        interpreted = probabilities
        default_threshold = settings.unconstrained_rejection_threshold
        threshold_source = "unconstrained_validation"
        eligible_indices = list(range(len(labels)))

    if allowed_labels is not None:
        label_allowlist = set(allowed_labels)
        eligible_indices = [
            index for index in eligible_indices if labels[index] in label_allowlist
        ]
        if not eligible_indices:
            scope = f"作物 {crop}" if crop else "当前输入"
            raise ValueError(f"知识库没有覆盖{scope}可识别的病害。")
        threshold_source += "_knowledge_filtered"

    eligible_classes = len(eligible_indices)
    covered_probability_mass = float(interpreted[eligible_indices].sum())

    threshold = rejection_threshold if rejection_threshold is not None else default_threshold
    count = min(top_k or settings.top_k, eligible_classes)
    indices = sorted(
        eligible_indices,
        key=lambda index: (-float(interpreted[index]), labels[index]),
    )[:count]
    predictions: list[dict[str, object]] = []
    for index in indices:
        confidence = float(interpreted[index])
        label = labels[index]
        predicted_crop, _, disease = label.partition("___")
        predictions.append(
            {
                "label": label,
                "display_label": display_label(label),
                "crop": predicted_crop,
                "crop_zh": display_crop(predicted_crop),
                "disease": disease,
                "disease_zh": display_disease(disease),
                "confidence": confidence,
            }
        )

    if not crop and settings.require_crop_confirmation:
        decision = settings.low_confidence_action
        decision_reason = "crop_confirmation_required"
    elif crop_probability_mass is not None and crop_probability_mass < settings.minimum_crop_probability_mass:
        decision = settings.low_confidence_action
        decision_reason = "crop_mismatch_or_unknown"
    elif float(predictions[0]["confidence"]) < threshold:
        decision = settings.low_confidence_action
        decision_reason = "low_confidence"
    else:
        decision = "accepted"
        decision_reason = "confidence_threshold_met"

    return {
        "crop_constraint": crop,
        "raw_prediction": {
            "label": labels[raw_index],
            "display_label": display_label(labels[raw_index]),
            "confidence": raw_confidence,
        },
        "rejection_threshold": threshold,
        "threshold_source": threshold_source,
        "crop_probability_mass": crop_probability_mass,
        "covered_probability_mass": covered_probability_mass,
        "minimum_crop_probability_mass": settings.minimum_crop_probability_mass,
        "decision": decision,
        "decision_reason": decision_reason,
        "decision_reason_zh": DECISION_REASON_NAMES_ZH[decision_reason],
        "predictions": predictions,
    }


class DiagnosisEngine:
    def __init__(
        self,
        config_path: Path,
        project_root: Path,
        device: str = "auto",
        model_override: Path | None = None,
    ) -> None:
        from ultralytics import YOLO

        self.settings = InferenceSettings.from_yaml(config_path, project_root)
        self.labels = self.settings.labels()
        self.model_path = (model_override or self.settings.model_path).resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        self.device = 0 if device == "cuda" or (
            device == "auto" and torch.cuda.is_available()
        ) else "cpu"
        self.model = YOLO(str(self.model_path))
        model_labels = [self.model.names[index] for index in range(len(self.model.names))]
        if model_labels != self.labels:
            raise RuntimeError("Model taxonomy does not match configured labels.json.")

    @property
    def crops(self) -> list[str]:
        return available_crops(self.labels)

    def predict_many(
        self,
        image_paths: Sequence[Path],
        crops: Sequence[str | None] | None = None,
        batch_size: int = 32,
        top_k: int | None = None,
        rejection_threshold: float | None = None,
        allowed_labels: Collection[str] | None = None,
    ) -> list[dict[str, object]]:
        if crops is None:
            crops = [None] * len(image_paths)
        if len(crops) != len(image_paths):
            raise ValueError("Each image must have exactly one crop constraint.")
        quality_reports = [assess_image(path, self.settings.quality) for path in image_paths]
        payloads: list[dict[str, object]] = []
        for offset in range(0, len(image_paths), batch_size):
            path_batch = list(image_paths[offset : offset + batch_size])
            crop_batch = list(crops[offset : offset + batch_size])
            quality_batch = quality_reports[offset : offset + batch_size]
            results = self.model.predict(
                source=[str(path) for path in path_batch],
                imgsz=self.settings.image_size,
                batch=len(path_batch),
                device=self.device,
                stream=False,
                verbose=False,
            )
            for path, crop, quality, result in zip(
                path_batch, crop_batch, quality_batch, results, strict=True
            ):
                if result.probs is None:
                    raise RuntimeError(f"No classification probabilities returned for {path}")
                interpreted = interpret_probabilities(
                    result.probs.data,
                    self.labels,
                    self.settings,
                    crop=crop,
                    top_k=top_k,
                    rejection_threshold=rejection_threshold,
                    allowed_labels=allowed_labels,
                )
                if not quality["passed"]:
                    interpreted["decision"] = self.settings.low_confidence_action
                    interpreted["decision_reason"] = "image_quality_failed"
                    interpreted["decision_reason_zh"] = DECISION_REASON_NAMES_ZH[
                        "image_quality_failed"
                    ]
                payloads.append(
                    {
                        "image": str(path.resolve()),
                        "model": str(self.model_path),
                        "device": "cuda" if self.device == 0 else "cpu",
                        "image_quality": quality,
                        **interpreted,
                    }
                )
        return payloads

    def predict(
        self,
        image_path: Path,
        crop: str | None = None,
        top_k: int | None = None,
        rejection_threshold: float | None = None,
        allowed_labels: Collection[str] | None = None,
    ) -> dict[str, object]:
        return self.predict_many(
            [image_path],
            [crop],
            batch_size=1,
            top_k=top_k,
            rejection_threshold=rejection_threshold,
            allowed_labels=allowed_labels,
        )[0]
