from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class QualitySettings:
    enabled: bool = True
    min_short_side: int = 96
    min_brightness: float = 25.0
    max_brightness: float = 235.0
    max_dark_fraction: float = 0.80
    max_bright_fraction: float = 0.80
    min_sharpness: float = 35.0

    @classmethod
    def from_mapping(cls, payload: dict[str, object] | None) -> "QualitySettings":
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", True)),
            min_short_side=int(payload.get("min_short_side", 96)),
            min_brightness=float(payload.get("min_brightness", 25.0)),
            max_brightness=float(payload.get("max_brightness", 235.0)),
            max_dark_fraction=float(payload.get("max_dark_fraction", 0.80)),
            max_bright_fraction=float(payload.get("max_bright_fraction", 0.80)),
            min_sharpness=float(payload.get("min_sharpness", 35.0)),
        )


ISSUE_MESSAGES_ZH = {
    "resolution_too_low": "图片分辨率过低，请靠近叶片重新拍摄",
    "too_dark": "图片过暗，请增加光线后重新拍摄",
    "too_bright": "图片过曝，请避开强光后重新拍摄",
    "too_blurry": "图片过于模糊，请对焦叶片后重新拍摄",
}


def laplacian_variance(gray: np.ndarray) -> float:
    if gray.ndim != 2 or min(gray.shape) < 3:
        return 0.0
    center = gray[1:-1, 1:-1] * -4.0
    laplacian = (
        center
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(laplacian.var())


def image_quality_metrics(image: Image.Image) -> dict[str, float | int]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    analysis = image.copy()
    analysis.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = np.asarray(analysis.convert("L"), dtype=np.float32)
    return {
        "width": width,
        "height": height,
        "short_side": min(width, height),
        "brightness_mean": float(gray.mean()),
        "dark_fraction": float((gray <= 15).mean()),
        "bright_fraction": float((gray >= 245).mean()),
        "sharpness": laplacian_variance(gray),
    }


def assess_metrics(
    metrics: dict[str, float | int], settings: QualitySettings
) -> dict[str, object]:
    issues: list[str] = []
    if int(metrics["short_side"]) < settings.min_short_side:
        issues.append("resolution_too_low")
    brightness = float(metrics["brightness_mean"])
    if brightness < settings.min_brightness or float(metrics["dark_fraction"]) > settings.max_dark_fraction:
        issues.append("too_dark")
    if brightness > settings.max_brightness or float(metrics["bright_fraction"]) > settings.max_bright_fraction:
        issues.append("too_bright")
    if float(metrics["sharpness"]) < settings.min_sharpness:
        issues.append("too_blurry")
    return {
        "passed": not issues,
        "issues": issues,
        "messages_zh": [ISSUE_MESSAGES_ZH[issue] for issue in issues],
        "metrics": metrics,
        "thresholds": {
            "min_short_side": settings.min_short_side,
            "min_brightness": settings.min_brightness,
            "max_brightness": settings.max_brightness,
            "max_dark_fraction": settings.max_dark_fraction,
            "max_bright_fraction": settings.max_bright_fraction,
            "min_sharpness": settings.min_sharpness,
        },
    }


def assess_image(path: Path, settings: QualitySettings) -> dict[str, object]:
    try:
        with Image.open(path) as image:
            metrics = image_quality_metrics(image)
    except Exception as error:
        raise ValueError(f"Cannot decode image {path}: {error}") from error
    if not settings.enabled:
        return {
            "passed": True,
            "issues": [],
            "messages_zh": [],
            "metrics": metrics,
            "thresholds": {},
        }
    return assess_metrics(metrics, settings)
