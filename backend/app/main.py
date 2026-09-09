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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crop_disease.advice import DeepSeekAdviceError
from crop_disease.advice import provider_catalog
from crop_disease.image_gate import ImageGateError
from fastapi.responses import JSONResponse
from app.database import check_database, create_tables, get_session
from app.models import DiagnosisRecord
from app.schemas import (
    ApiProviderOption,
    ApiProviderTestResponse,
    CropOption,
    DiagnosisRecordResponse,
    HistoryResponse,
)
from app.services import service


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
    create_tables()
    yield


app = FastAPI(
    title="农作物病虫害智能诊疗 API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(ImageGateError)
async def image_gate_error_handler(_, error: ImageGateError) -> JSONResponse:
    # Keep detail as a string for existing ArkTS/web error handling.
    return JSONResponse(status_code=error.status_code,
                        content={"detail": error.message, "code": error.code})


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
    client_id: str = Form(...),
    crop: str = Form(...),
    symptom_description: str | None = Form(None),
    api_provider: str | None = Form(None),
    api_base_url: str | None = Form(None),
    api_model: str | None = Form(None),
    api_key: str | None = Form(None),
    session: Session = Depends(get_session),
) -> DiagnosisRecordResponse:
    normalized_client_id = validate_uuid(client_id)
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
    record = DiagnosisRecord(
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
    client_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> HistoryResponse:
    normalized_client_id = validate_uuid(client_id)
    total = session.scalar(
        select(func.count(DiagnosisRecord.id)).where(
            DiagnosisRecord.client_id == normalized_client_id
        )
    ) or 0
    records = session.scalars(
        select(DiagnosisRecord)
        .where(DiagnosisRecord.client_id == normalized_client_id)
        .order_by(DiagnosisRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return HistoryResponse(items=[to_response(record) for record in records], total=total)


@app.get("/api/diagnoses/{record_id}", response_model=DiagnosisRecordResponse)
def diagnosis_detail(
    record_id: str,
    client_id: str = Query(...),
    session: Session = Depends(get_session),
) -> DiagnosisRecordResponse:
    normalized_client_id = validate_uuid(client_id)
    normalized_record_id = validate_uuid(record_id, "record_id")
    record = session.scalar(
        select(DiagnosisRecord).where(
            DiagnosisRecord.id == normalized_record_id,
            DiagnosisRecord.client_id == normalized_client_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="找不到该诊断记录。")
    return to_response(record)
