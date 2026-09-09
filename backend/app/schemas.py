from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DiseaseOption(BaseModel):
    label: str
    name: str


class CropOption(BaseModel):
    key: str
    name: str
    diseases: list[DiseaseOption]


class ApiProviderOption(BaseModel):
    id: str
    name: str
    base_url: str
    default_model: str
    description: str
    custom: bool


class ApiProviderTestResponse(BaseModel):
    status: str
    provider: str
    model: str
    request_url: str
    latency_ms: int = Field(ge=0)


class KnowledgeSourceResponse(BaseModel):
    source_id: str
    title: str
    source_org: str
    source_url: str
    retrieval_score: float | None = None


class DiagnosisRecordResponse(BaseModel):
    id: str
    crop: str
    crop_zh: str
    symptom_description: str | None
    original_filename: str
    disease_zh: str
    likelihood_percent: float
    decision: str
    advice: dict[str, Any]
    report_text: str
    knowledge_sources: list[KnowledgeSourceResponse]
    created_at: datetime


class HistoryResponse(BaseModel):
    items: list[DiagnosisRecordResponse]
    total: int = Field(ge=0)
