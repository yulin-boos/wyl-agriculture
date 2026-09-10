from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from app.knowledge import DuplicateKnowledgeError, KnowledgeInput
from app.catalog import read_knowledge
from app.database import SessionLocal
from app.models import Crop, Disease, KnowledgeRecord
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
)
from crop_disease.rag import ChunkedKnowledgeBase, RagSettings
from crop_disease.image_gate import AgriculturalImageGate, GateSettings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "inference.yaml"


class DiagnosisWebService:
    def __init__(self) -> None:
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._knowledge_lock = threading.RLock()
        self._engine: DiagnosisEngine | None = None
        self.image_gate = AgriculturalImageGate(GateSettings.from_env(PROJECT_ROOT))
        self.inference_settings = InferenceSettings.from_yaml(CONFIG_PATH, PROJECT_ROOT)
        self.advice_settings = DeepSeekSettings.from_yaml(CONFIG_PATH)
        self.advice_client = DeepSeekAdviceClient(self.advice_settings)
        self.rag_settings = RagSettings.from_yaml(CONFIG_PATH, PROJECT_ROOT)
        self.knowledge_base = None
        self._knowledge_entries = None
        self.covered_labels = frozenset()
        self.covered_crops = frozenset()

    def _refresh_knowledge(self) -> None:
        with SessionLocal() as session:
            entries = read_knowledge(session)
        if entries != self._knowledge_entries:
            self._install_knowledge(entries)

    def _install_knowledge(self, entries) -> None:
        labels = frozenset(entry.label for entry in entries)
        if labels - set(self.inference_settings.labels()):
            raise ValueError("数据库包含模型不支持的病害标签。")
        knowledge = ChunkedKnowledgeBase(entries, self.rag_settings.chunk_size_chars) if entries else None
        self.knowledge_base = knowledge
        self.covered_labels = labels
        self.covered_crops = frozenset(entry.crop for entry in entries)
        self._knowledge_entries = entries

    def add_knowledge(self, item: KnowledgeInput, session: Session) -> None:
        if item.label not in self.inference_settings.labels():
            raise ValueError("病害标签不在模型支持范围内。")
        if item.crop != item.label.partition("___")[0]:
            raise ValueError("作物与病害标签不匹配。")
        disease = session.scalar(select(Disease).where(Disease.model_label == item.label))
        if disease is None:
            raise ValueError("数据库病害分类尚未初始化。")
        crop = session.get(Crop, disease.crop_id)
        if crop is None or crop.crop_key != item.crop or crop.status != "active":
            raise ValueError("作物不存在或已停用。")
        if item.crop_zh != crop.name_zh or item.disease_zh != disease.name_zh:
            raise ValueError("作物和病害中文名必须与数据库分类一致，请重新获取模板。")
        if session.scalar(select(KnowledgeRecord.id).where(KnowledgeRecord.source_code == item.id)):
            raise DuplicateKnowledgeError("来源 ID 已存在，请使用新的 id。")
        record = KnowledgeRecord(
            disease_id=disease.id, source_code=item.id, title=item.title,
            content=item.content, tags=item.tags, source_org=item.source_org,
            source_url=str(item.source_url), source_updated=item.source_updated,
        )
        try:
            session.add(record)
            session.flush()
            entries = read_knowledge(session)
            # Validate the full candidate index before committing the new source.
            ChunkedKnowledgeBase(entries, self.rag_settings.chunk_size_chars)
            session.commit()
        except IntegrityError as error:
            session.rollback()
            if session.scalar(select(KnowledgeRecord.id).where(KnowledgeRecord.source_code == item.id)):
                raise DuplicateKnowledgeError("来源 ID 已存在，请使用新的 id。") from error
            raise
        except Exception:
            session.rollback()
            raise
        # All workers observe the committed catalog on their next read.
        with self._knowledge_lock:
            self._knowledge_entries = None

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
        with self._knowledge_lock:
            self._refresh_knowledge()
            knowledge = self.knowledge_base
        diseases_by_crop: dict[str, dict[str, str]] = {}
        crop_names = {}
        for entry in (knowledge.entries if knowledge else []):
            crop_names[entry.crop] = entry.crop_zh
            diseases_by_crop.setdefault(entry.crop, {})[entry.label] = entry.disease_zh
        return [
            {
                "key": crop,
                "name": crop_names[crop],
                "diseases": [
                    {"label": label, "name": disease_name}
                    for label, disease_name in sorted(diseases_by_crop[crop].items())
                ],
            }
            for crop in diseases_by_crop
        ]

    def supports_crop(self, crop: str) -> bool:
        with self._knowledge_lock:
            self._refresh_knowledge()
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
        with self._knowledge_lock:
            knowledge = self.knowledge_base
            covered_labels = self.covered_labels
        image_validation = self.image_gate.check(image_path)
        with self._inference_lock:
            diagnosis = self.engine.predict(
                image_path,
                crop=crop,
                allowed_labels=covered_labels,
            )
        diagnosis["image_validation"] = image_validation
        diagnosis["user_context"] = user_context
        hits = knowledge.retrieve_for_diagnosis(
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
