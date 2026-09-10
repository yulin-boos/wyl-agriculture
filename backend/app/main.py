from __future__ import annotations

import os
import logging
import tempfile
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from crop_disease.advice import DeepSeekAdviceError
from crop_disease.advice import provider_catalog
from crop_disease.image_gate import ImageGateError
from fastapi.responses import JSONResponse
from app.database import check_database, check_schema, get_session
from app.models import Crop, Disease, DiagnosisFeedback, DiagnosisRecord, User
from app.auth import optional_user, router as auth_router
from pydantic import BaseModel, ConfigDict, Field
from app.schemas import (
    ApiProviderOption,
    ApiProviderTestResponse,
    CropOption,
    DiagnosisRecordResponse,
    HistoryResponse,
)
from app.services import service
from app.admin import router as admin_router


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
LOGGER = logging.getLogger(__name__)
LOCAL_DEVELOPMENT_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def allowed_origins() -> list[str]:
    value = os.getenv("WEB_ALLOWED_ORIGINS", "")
    configured = [origin.strip() for origin in value.split(",") if origin.strip()]
    return list(dict.fromkeys([*configured, *LOCAL_DEVELOPMENT_ORIGINS]))


@asynccontextmanager
async def lifespan(_: FastAPI):
    check_schema()
    yield


app = FastAPI(
    title="农作物病虫害智能诊疗 API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(admin_router)
app.include_router(auth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.exception_handler(ImageGateError)
async def image_gate_error_handler(_, error: ImageGateError) -> JSONResponse:
    # Keep detail as a string for existing ArkTS/web error handling.
    return JSONResponse(status_code=error.status_code,
                        content={"detail": error.message, "code": error.code})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_, error: SQLAlchemyError) -> JSONResponse:
    LOGGER.error("Database operation failed: %s", type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": "数据库操作失败，请检查数据库配置后重试。"})


def owner_filter(user: User | None, client_id: str | None):
    if user is not None:
        return DiagnosisRecord.user_id == user.id
    if not client_id:
        raise HTTPException(status_code=422, detail="请登录或提供 client_id。")
    return and_(DiagnosisRecord.user_id.is_(None), DiagnosisRecord.client_id == validate_uuid(client_id))


def validate_uuid(value: str, field_name: str = "client_id") -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{field_name} 格式不正确。") from error


def build_user_context(
    symptom_description: str | None,
) -> dict[str, object]:
    context: dict[str, object] = {}
    symptom = (symptom_description or "").strip()
    if len(symptom) > 1000:
        raise HTTPException(status_code=422, detail="症状描述不能超过1000字。")
    if symptom:
        context["symptom_description"] = symptom
    return context


def to_response(record: DiagnosisRecord) -> DiagnosisRecordResponse:
    advice = dict(record.advice_json)
    return DiagnosisRecordResponse(
        id=record.id,
        crop=record.crop,
        crop_zh=record.crop_zh,
        symptom_description=record.symptom_description,
        original_filename=record.original_filename,
        disease_zh=record.disease_zh,
        likelihood_percent=float(advice.get("likelihood_percent", 0)),
        decision=record.decision,
        advice=advice,
        report_text=record.report_text,
        knowledge_sources=advice.get("knowledge_sources", []),
        created_at=record.created_at,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        check_database()
    except Exception as error:
        raise HTTPException(status_code=503, detail="数据库连接失败。") from error
    return {"status": "ok", "database": "ok"}


@app.get("/api/providers", response_model=list[ApiProviderOption])
def providers() -> list[dict[str, object]]:
    return provider_catalog()


@app.post("/api/providers/test", response_model=ApiProviderTestResponse)
async def test_provider(
    api_provider: str = Form(...),
    api_model: str = Form(...),
    api_key: str = Form(...),
    api_base_url: str | None = Form(None),
) -> dict[str, object]:
    if not api_key.strip():
        raise HTTPException(status_code=422, detail="请填写 API 密钥。")
    try:
        return await run_in_threadpool(
            service.test_provider,
            api_key,
            api_provider,
            api_base_url,
            api_model,
        )
    except DeepSeekAdviceError as error:
        configuration_errors = {
            "missing_api_key",
            "invalid_api_key_format",
            "unknown_provider",
            "invalid_base_url",
            "insecure_base_url",
            "private_base_url",
            "unresolvable_base_url",
            "invalid_model",
        }
        status_code = 422 if error.code in configuration_errors else 502
        raise HTTPException(status_code=status_code, detail=error.message_zh) from error


@app.get("/api/crops", response_model=list[CropOption])
def crops() -> list[dict[str, str]]:
    return service.crops()


@app.post("/api/diagnoses", response_model=DiagnosisRecordResponse, status_code=201)
async def create_diagnosis(
    image: UploadFile = File(...),
    client_id: str | None = Form(None),
    crop: str = Form(...),
    symptom_description: str | None = Form(None),
    api_provider: str | None = Form(None),
    api_base_url: str | None = Form(None),
    api_model: str | None = Form(None),
    api_key: str | None = Form(None),
    session: Session = Depends(get_session),
    user: User | None = Depends(optional_user),
) -> DiagnosisRecordResponse:
    owner_filter(user, client_id)
    normalized_client_id = validate_uuid(client_id) if client_id else None
    suffix = Path(image.filename or "image.jpg").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WEBP 或 BMP 图片。")
    max_bytes = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024
    content = await image.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="上传图片为空。")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="图片超过允许的大小。")
    user_context = build_user_context(symptom_description)
    if not service.supports_crop(crop):
        raise HTTPException(
            status_code=422,
            detail="当前知识库暂未覆盖所选作物，请从网页列表中重新选择。",
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        diagnosis, advice, report_text = await run_in_threadpool(
            service.diagnose,
            temporary_path,
            crop,
            user_context,
            api_key,
            api_provider,
            api_base_url,
            api_model,
        )
    except ImageGateError as error:
        if error.status_code == 503:
            LOGGER.exception("Image content validation unavailable")
        raise
    except DeepSeekAdviceError as error:
        raise HTTPException(status_code=502, detail=error.message_zh) from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        LOGGER.exception("Diagnosis processing failed")
        raise HTTPException(status_code=500, detail="诊断处理失败，请稍后重试。") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    prediction = diagnosis["predictions"][0]
    disease = session.scalar(select(Disease).where(Disease.model_label == str(prediction["label"])))
    if disease is None:
        raise HTTPException(status_code=422, detail="数据库中缺少识别标签，请先初始化分类数据。")
    catalog_crop = session.get(Crop, disease.crop_id)
    if catalog_crop is None or catalog_crop.crop_key != crop:
        raise HTTPException(status_code=422, detail="识别结果与所选作物不匹配。")
    record = DiagnosisRecord(
        user_id=user.id if user else None,
        crop_id=disease.crop_id,
        disease_id=disease.id,
        client_id=normalized_client_id,
        crop=str(prediction.get("crop") or crop),
        crop_zh=str(prediction.get("crop_zh") or crop),
        symptom_description=str(user_context.get("symptom_description") or "") or None,
        original_filename=Path(image.filename or "image").name[:255],
        model_label=str(prediction["label"]),
        disease_zh=str(prediction.get("disease_zh") or prediction["label"]),
        confidence=Decimal(str(prediction["confidence"])),
        decision=str(diagnosis["decision"]),
        diagnosis_json=diagnosis,
        advice_json=advice,
        report_text=report_text,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return to_response(record)


@app.get("/api/diagnoses", response_model=HistoryResponse)
def diagnosis_history(
    client_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: User | None = Depends(optional_user),
) -> HistoryResponse:
    ownership = owner_filter(user, client_id)
    total = session.scalar(
        select(func.count(DiagnosisRecord.id)).where(
            ownership
        )
    ) or 0
    records = session.scalars(
        select(DiagnosisRecord)
        .where(ownership)
        .order_by(DiagnosisRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return HistoryResponse(items=[to_response(record) for record in records], total=total)


@app.get("/api/diagnoses/{record_id}", response_model=DiagnosisRecordResponse)
def diagnosis_detail(
    record_id: str,
    client_id: str | None = Query(None),
    session: Session = Depends(get_session),
    user: User | None = Depends(optional_user),
) -> DiagnosisRecordResponse:
    ownership = owner_filter(user, client_id)
    normalized_record_id = validate_uuid(record_id, "record_id")
    record = session.scalar(
        select(DiagnosisRecord).where(
            DiagnosisRecord.id == normalized_record_id,
            ownership,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="找不到该诊断记录。")
    return to_response(record)


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    is_correct: bool = Field(strict=True)
    corrected_disease_id: int | None = Field(default=None, gt=0)
    content: str | None = Field(default=None, max_length=2000)


def owned_record(record_id: str, client_id: str | None, user: User | None, session: Session):
    record = session.scalar(select(DiagnosisRecord).where(
        DiagnosisRecord.id == validate_uuid(record_id, "record_id"), owner_filter(user, client_id)
    ))
    if record is None:
        raise HTTPException(status_code=404, detail="找不到该诊断记录。")
    return record


@app.get("/api/diseases")
def disease_catalog(crop: str | None = None, session: Session = Depends(get_session)):
    statement = select(Disease, Crop).join(Crop).where(Crop.status == "active")
    if crop:
        statement = statement.where(Crop.crop_key == crop)
    return [{"id": disease.id, "label": disease.model_label, "name": disease.name_zh,
             "crop": plant.crop_key, "category": disease.category}
            for disease, plant in session.execute(statement.order_by(Disease.model_class_index))]


@app.post("/api/diagnoses/{record_id}/feedback", status_code=201)
def add_feedback(record_id: str, data: FeedbackInput, client_id: str | None = Query(None),
                 session: Session = Depends(get_session), user: User | None = Depends(optional_user)):
    history = owned_record(record_id, client_id, user, session)
    if data.corrected_disease_id is not None:
        corrected = session.get(Disease, data.corrected_disease_id)
        if data.is_correct or corrected is None or corrected.crop_id != history.crop_id or corrected.id == history.disease_id:
            raise HTTPException(status_code=422, detail="修正病害必须属于同一作物且不同于原诊断，并将 is_correct 设为 false。")
    feedback = DiagnosisFeedback(
        history_id=history.id, user_id=history.user_id, client_id=history.client_id,
        is_correct=data.is_correct, corrected_disease_id=data.corrected_disease_id, content=data.content,
    )
    try:
        session.add(feedback)
        session.commit()
        session.refresh(feedback)
    except IntegrityError as error:
        session.rollback()
        if session.scalar(select(DiagnosisFeedback.id).where(DiagnosisFeedback.history_id == history.id)):
            raise HTTPException(status_code=409, detail="该诊断已提交反馈。") from error
        raise
    return {"id": feedback.id, "history_id": feedback.history_id, **data.model_dump()}


@app.get("/api/diagnoses/{record_id}/feedback")
def get_feedback(record_id: str, client_id: str | None = Query(None),
                 session: Session = Depends(get_session), user: User | None = Depends(optional_user)):
    history = owned_record(record_id, client_id, user, session)
    feedback = session.scalar(select(DiagnosisFeedback).where(DiagnosisFeedback.history_id == history.id))
    if feedback is None:
        raise HTTPException(status_code=404, detail="暂无反馈。")
    return {"id": feedback.id, "history_id": history.id, "is_correct": feedback.is_correct,
            "corrected_disease_id": feedback.corrected_disease_id, "content": feedback.content}


@app.delete("/api/diagnoses/{record_id}", status_code=204)
def delete_diagnosis(record_id: str, client_id: str | None = Query(None),
                     session: Session = Depends(get_session), user: User | None = Depends(optional_user)):
    history = owned_record(record_id, client_id, user, session)
    session.execute(delete(DiagnosisRecord).where(DiagnosisRecord.id == history.id))
    session.commit()
