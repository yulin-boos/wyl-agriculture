from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.knowledge import DuplicateKnowledgeError, KnowledgeInput
from app.services import service
from crop_disease.rag import KnowledgeBaseError
from app.database import get_session
from app.models import Crop, Disease
from app.auth import token_user


LOGGER = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(get_session)) -> None:
    expected = os.getenv("ADMIN_API_TOKEN", "").strip()
    if credentials is None:
        raise HTTPException(status_code=401, detail="管理员凭证无效。", headers={"WWW-Authenticate": "Bearer"})
    if expected and hmac.compare_digest(credentials.credentials.encode("utf-8"), expected.encode("utf-8")):
        return
    user = token_user(credentials.credentials, session)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")


router = APIRouter(prefix="/api/admin/knowledge", tags=["管理员知识库"], dependencies=[Depends(require_admin)])


@router.get("/labels")
def labels(session: Session = Depends(get_session)) -> list[dict[str, str]]:
    return [
        {"label": disease.model_label, "crop": crop.crop_key,
         "crop_zh": crop.name_zh, "disease_zh": disease.name_zh}
        for disease, crop in session.execute(select(Disease, Crop).join(Crop).where(Crop.status == "active").order_by(Disease.model_class_index))
        if disease.model_label in service.inference_settings.labels()
    ]


@router.get("/template")
def template(label: str = Query(..., description="从 /labels 中选择模型病害标签"), session: Session = Depends(get_session)) -> dict:
    selected = next((item for item in labels(session) if item["label"] == label), None)
    if selected is None:
        raise HTTPException(status_code=422, detail="病害标签不在模型支持范围内。")
    return {
        "id": "", **selected, "title": "", "source_org": "",
        "source_url": "", "source_updated": "", "tags": [], "content": "",
    }


@router.post("", status_code=201, response_model=KnowledgeInput)
def create_knowledge(item: KnowledgeInput, session: Session = Depends(get_session)) -> KnowledgeInput:
    try:
        service.add_knowledge(item, session)
    except DuplicateKnowledgeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (SQLAlchemyError, OSError, KnowledgeBaseError) as error:
        session.rollback()
        LOGGER.exception("Knowledge update failed")
        raise HTTPException(status_code=503, detail="知识库保存失败，请检查存储状态后重试。") from error
    return item
