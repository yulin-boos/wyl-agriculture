from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from crop_disease.advice import (
    DeepSeekAdviceClient,
    DeepSeekSettings,
    format_advice,
    settings_for_provider,
)
from crop_disease.credential_store import DEFAULT_CREDENTIAL_PATH, load_api_key
from crop_disease.diagnosis import (
    DiagnosisEngine,
    InferenceSettings,
    available_crops,
    display_crop,
)
from crop_disease.rag import ChunkedKnowledgeBase, RagSettings
from crop_disease.image_gate import AgriculturalImageGate, GateSettings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "inference.yaml"


class DiagnosisWebService:
    def __init__(self) -> None:
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._engine: DiagnosisEngine | None = None
        self.image_gate = AgriculturalImageGate(GateSettings.from_env(PROJECT_ROOT))
        self.inference_settings = InferenceSettings.from_yaml(CONFIG_PATH, PROJECT_ROOT)
        self.advice_settings = DeepSeekSettings.from_yaml(CONFIG_PATH)
        self.advice_client = DeepSeekAdviceClient(self.advice_settings)
        self.rag_settings = RagSettings.from_yaml(CONFIG_PATH, PROJECT_ROOT)
        self.knowledge_base = ChunkedKnowledgeBase.from_jsonl(
            self.rag_settings.corpus_path,
            self.rag_settings.chunk_size_chars,
        )
        model_labels = set(self.inference_settings.labels())
        knowledge_labels = set(self.knowledge_base.coverage_labels())
        unknown_labels = knowledge_labels - model_labels
        if unknown_labels:
            raise RuntimeError(
                "知识库包含模型标签体系之外的标签："
                + ", ".join(sorted(unknown_labels))
            )
        self.covered_labels = frozenset(knowledge_labels)
        self.covered_crops = frozenset(
            available_crops(sorted(self.covered_labels))
        )

    @property
    def engine(self) -> DiagnosisEngine:
        if self._engine is None:
            with self._load_lock:
                if self._engine is None:
                    self._engine = DiagnosisEngine(
                        config_path=CONFIG_PATH,
                        project_root=PROJECT_ROOT,
                        device=os.getenv("INFERENCE_DEVICE", "auto"),
                    )
        return self._engine

    def crops(self) -> list[dict[str, object]]:
        diseases_by_crop: dict[str, dict[str, str]] = {}
        for entry in self.knowledge_base.entries:
            diseases_by_crop.setdefault(entry.crop, {})[entry.label] = entry.disease_zh
        return [
            {
                "key": crop,
                "name": display_crop(crop),
                "diseases": [
                    {"label": label, "name": disease_name}
                    for label, disease_name in sorted(diseases_by_crop[crop].items())
                ],
            }
            for crop in sorted(self.covered_crops)
        ]

    def supports_crop(self, crop: str) -> bool:
        return crop in self.covered_crops

    def api_key(self) -> str | None:
        environment_key = os.getenv(self.advice_settings.api_key_env, "").strip()
        if environment_key:
            return environment_key
        return load_api_key(PROJECT_ROOT / DEFAULT_CREDENTIAL_PATH)

    def test_provider(
        self,
        api_key: str,
        api_provider: str,
        api_base_url: str | None = None,
        api_model: str | None = None,
    ) -> dict[str, object]:
        provider_settings = settings_for_provider(
            self.advice_settings,
            api_provider,
            base_url=api_base_url,
            model=api_model,
        )
        return DeepSeekAdviceClient(provider_settings).test_connection(api_key)

    def diagnose(
        self,
        image_path: Path,
        crop: str,
        user_context: dict[str, object],
        api_key: str | None = None,
        api_provider: str | None = None,
        api_base_url: str | None = None,
        api_model: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        if not self.supports_crop(crop):
            raise ValueError("当前知识库暂未覆盖所选作物，请选择网页列出的作物。")
        image_validation = self.image_gate.check(image_path)
        with self._inference_lock:
            diagnosis = self.engine.predict(
                image_path,
                crop=crop,
                allowed_labels=self.covered_labels,
            )
        diagnosis["image_validation"] = image_validation
        diagnosis["user_context"] = user_context
        hits = self.knowledge_base.retrieve_for_diagnosis(
            diagnosis, top_k=self.rag_settings.top_k
        )
        if not hits:
            raise ValueError("当前识别候选没有对应的知识库资料，已停止生成诊疗建议。")
        provider_settings = settings_for_provider(
            self.advice_settings,
            api_provider,
            base_url=api_base_url,
            model=api_model,
        )
        advice_client = (
            self.advice_client
            if provider_settings == self.advice_settings
            else DeepSeekAdviceClient(provider_settings)
        )
        fallback_key = self.api_key() if provider_settings.provider_id == "deepseek" else None
        advice = advice_client.generate(
            diagnosis,
            explicit_api_key=api_key if api_key is not None else fallback_key,
            evidence=[hit.to_prompt_dict() for hit in hits],
        )
        return diagnosis, advice, format_advice(advice)


service = DiagnosisWebService()
