from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DiagnosisRecord(Base):
    __tablename__ = "diagnosis_records"
    __table_args__ = (
        Index("idx_diagnosis_client_created", "client_id", "created_at"),
        Index("idx_diagnosis_crop_created", "crop", "created_at"),
        Index("idx_diagnosis_label_created", "model_label", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    crop: Mapped[str] = mapped_column(String(80), nullable=False)
    crop_zh: Mapped[str] = mapped_column(String(80), nullable=False)
    symptom_description: Mapped[str | None] = mapped_column(String(1000))
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000))
    model_label: Mapped[str] = mapped_column(String(255), nullable=False)
    disease_zh: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    diagnosis_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    advice_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
