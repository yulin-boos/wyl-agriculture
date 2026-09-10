"""Seed data and database-backed RAG catalog."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Crop, Disease, KnowledgeRecord
from crop_disease.diagnosis import display_crop, display_disease
from crop_disease.rag import KnowledgeEntry

ROOT = Path(__file__).resolve().parents[1]


def seed_rows():
    labels = json.loads((ROOT / "data/labels.json").read_text(encoding="utf-8"))["label_to_id"]
    crop_keys = sorted({label.partition("___")[0] for label in labels})
    crops = [dict(id=i + 1, crop_key=key, name_zh=display_crop(key), status="active", sort_order=i)
             for i, key in enumerate(crop_keys)]
    crop_ids = {row["crop_key"]: row["id"] for row in crops}
    diseases = []
    for label, index in sorted(labels.items(), key=lambda pair: pair[1]):
        crop, _, disease = label.partition("___")
        category = "healthy" if disease == "healthy" else "pest" if "mite" in disease.lower() else "disease"
        diseases.append(dict(id=index + 1, crop_id=crop_ids[crop], model_class_index=index,
                             model_label=label, name_zh=display_disease(disease), category=category))
    from crop_disease.rag import RagSettings
    path = RagSettings.from_yaml(ROOT / "configs/inference.yaml", ROOT).corpus_path
    knowledge = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        knowledge.append(dict(
            disease_id=labels[entry["label"]] + 1, source_code=entry["id"],
            title=entry["title"], content=entry["content"], tags=entry["tags"],
            source_org=entry["source_org"], source_url=entry["source_url"],
            source_updated=entry.get("source_updated", ""),
        ))
    return crops, diseases, knowledge


def seed_database(session: Session) -> None:
    """Explicit initialization only; existing rows are never overwritten."""
    crops, diseases, knowledge = seed_rows()
    crop_ids = {}
    for row in crops:
        obj = session.scalar(select(Crop).where(Crop.crop_key == row["crop_key"]))
        if obj is None:
            obj = Crop(**{key: value for key, value in row.items() if key != "id"})
            session.add(obj)
            session.flush()
        crop_ids[row["id"]] = obj.id
    disease_ids = {}
    for row in diseases:
        obj = session.scalar(select(Disease).where(Disease.model_label == row["model_label"]))
        if obj is None:
            obj = Disease(**{**{key: value for key, value in row.items() if key != "id"},
                             "crop_id": crop_ids[row["crop_id"]]})
            session.add(obj)
            session.flush()
        if obj.model_class_index != row["model_class_index"] or obj.crop_id != crop_ids[row["crop_id"]]:
            raise ValueError("数据库病害分类与模型标签不一致。")
        disease_ids[row["id"]] = obj.id
    for row in knowledge:
        if session.scalar(select(KnowledgeRecord.id).where(KnowledgeRecord.source_code == row["source_code"])) is None:
            session.add(KnowledgeRecord(**{**row, "disease_id": disease_ids[row["disease_id"]]}))
    session.flush()


def read_knowledge(session: Session) -> list[KnowledgeEntry]:
    rows = session.execute(
        select(KnowledgeRecord, Disease, Crop)
        .join(Disease, KnowledgeRecord.disease_id == Disease.id)
        .join(Crop, Disease.crop_id == Crop.id)
        .where(Crop.status == "active")
        .order_by(Crop.sort_order, Crop.crop_key, KnowledgeRecord.id)
    ).all()
    return [KnowledgeEntry(
        id=record.source_code, label=disease.model_label, crop=crop.crop_key,
        crop_zh=crop.name_zh, disease_zh=disease.name_zh, title=record.title,
        source_org=record.source_org, source_url=record.source_url,
        source_updated=record.source_updated, content=record.content, tags=record.tags or [],
    ) for record, disease, crop in rows]
