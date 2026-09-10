from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    raise RuntimeError("请设置 DATABASE_URL 指向 hezhen_db；测试可显式使用 SQLite。")


def engine_connect_args(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    arguments: dict[str, object] = {
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }
    ssl_ca = os.getenv("MYSQL_SSL_CA", "").strip()
    if ssl_ca and url.startswith("mysql"):
        arguments["ssl"] = {"ca": ssl_ca, "check_hostname": True}
    return arguments


DATABASE_URL = database_url()
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args=engine_connect_args(DATABASE_URL),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


class Base(DeclarativeBase):
    pass


def create_tables() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_schema() -> None:
    from sqlalchemy import inspect
    from app.models import Base
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise RuntimeError("数据库尚未初始化，请先导入禾诊_MySQL初始化.sql。")
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        if set(table.columns.keys()) - actual:
            raise RuntimeError(f"数据库表 {table.name} 字段不完整，请按配套架构迁移。")


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
