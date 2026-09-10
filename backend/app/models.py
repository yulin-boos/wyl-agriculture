from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from app.database import Base


ID_TYPE = BigInteger().with_variant(Integer, "sqlite")
TABLE_OPTIONS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        TABLE_OPTIONS,
    )
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class Crop(Base):
    __tablename__ = "crops"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="ck_crops_status"), TABLE_OPTIONS)
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    crop_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_zh: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class Disease(Base):
    __tablename__ = "diseases"
    __table_args__ = (CheckConstraint("model_class_index >= 0", name="ck_diseases_class_index"), TABLE_OPTIONS)
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_class_index: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    model_label: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)


class KnowledgeRecord(Base):
    __tablename__ = "knowledge_base"
    __table_args__ = (TABLE_OPTIONS,)
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), 'mysql'), nullable=False)
    tags: Mapped[list | None] = mapped_column(JSON)
    source_org: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_updated: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class DiagnosisRecord(Base):
    __tablename__ = "diagnosis_history"
    __table_args__ = (
        Index("idx_diagnosis_client_created", "client_id", "created_at"),
        Index("idx_diagnosis_crop_created", "crop", "created_at"),
        Index("idx_diagnosis_label_created", "model_label", "created_at"),
        Index("idx_diagnosis_user_created", "user_id", "created_at"),
        CheckConstraint("user_id IS NOT NULL OR (client_id IS NOT NULL AND length(trim(client_id)) > 0)", name="ck_history_owner"),
        TABLE_OPTIONS,
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id", ondelete="RESTRICT"), nullable=False, index=True)
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id", ondelete="RESTRICT"), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(String(36))
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


class DiagnosisFeedback(Base):
    __tablename__ = "diagnosis_feedback"
    __table_args__ = (
        CheckConstraint("user_id IS NOT NULL OR (client_id IS NOT NULL AND length(trim(client_id)) > 0)", name="ck_feedback_owner"),
        CheckConstraint("is_correct IN (0, 1)", name="ck_feedback_correct"),
        TABLE_OPTIONS,
    )
    id: Mapped[int] = mapped_column(ID_TYPE, primary_key=True, autoincrement=True)
    history_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_history.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    corrected_disease_id: Mapped[int | None] = mapped_column(ForeignKey("diseases.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(36))
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
