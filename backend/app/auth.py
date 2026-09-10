from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import User

bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["用户账户"])


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value is None:
            return None
        value = value.strip().lower()
        if not value or value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value):
            raise ValueError("邮箱格式不正确")
        return value


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != 600000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def signing_key() -> bytes:
    key = os.getenv("AUTH_SECRET_KEY", "")
    if len(key.encode()) < 32:
        raise HTTPException(status_code=503, detail="请先配置至少 32 字节的 AUTH_SECRET_KEY。")
    return key.encode()


def issue_token(user: User) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user.id, "exp": int(time.time()) + 86400}).encode()).decode().rstrip("=")
    signature = hmac.new(signing_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def token_user(token: str, session: Session) -> User:
    key = signing_key()
    try:
        payload, signature = token.split(".")
        if not hmac.compare_digest(hmac.new(key, payload.encode(), hashlib.sha256).hexdigest(), signature):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] <= time.time():
            raise ValueError()
        user = session.get(User, int(data["sub"]))
        if user is None or user.status != "active":
            raise ValueError()
        return user
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。", headers={"WWW-Authenticate": "Bearer"})


def optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                  session: Session = Depends(get_session)) -> User | None:
    return token_user(credentials.credentials, session) if credentials else None


def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email, "role": user.role, "status": user.status}


@router.post("/register", status_code=201)
def register(data: RegisterInput, session: Session = Depends(get_session)):
    signing_key()
    user = User(username=data.username.lower(), email=data.email, password_hash=hash_password(data.password), role="user", status="active")
    try:
        session.add(user)
        session.commit()
        session.refresh(user)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="用户名或邮箱已存在。") from error
    return public_user(user)


@router.post("/login")
def login(data: LoginInput, session: Session = Depends(get_session)):
    signing_key()
    user = session.scalar(select(User).where(User.username == data.username.lower()))
    # Run the same password work for unknown usernames.
    encoded = user.password_hash if user else "pbkdf2_sha256$600000$unknown$" + "0" * 64
    valid = verify_password(data.password, encoded)
    if not valid or user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="用户名或密码错误，或账户已停用。")
    return {"access_token": issue_token(user), "token_type": "bearer", "expires_in": 86400, "user": public_user(user)}


@router.get("/me")
def me(user: User | None = Depends(optional_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return public_user(user)
