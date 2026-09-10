"""Generate the deliverable from the same metadata and seeds used by the API."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable
from app.database import Base
from app import models
from app.catalog import seed_rows


def literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    # NO_BACKSLASH_ESCAPES is set below, so SQL quote doubling is sufficient.
    return "'" + value.replace("'", "''") + "'"


def build_sql():
    dialect = mysql.dialect()
    parts = ["""-- 禾诊 MySQL 初始化脚本
-- 来源：禾诊_SQL数据库架构图.pptx；6 张核心表、8 条外键。
-- 适用 MySQL 8.0.16+（需要实际执行 CHECK 约束），UTF-8。
-- 图中仅列关键字段；补充现有诊断接口所需快照、来源与时间字段。
-- 新库初始化使用；已有同名但结构不同的表不会自动升级。
-- 不删除数据库或旧 diagnosis_records；不预置账户或明文密码。
-- DDL 会隐式提交。先备份已有库，再执行；不要使用忽略错误的 --force。
SET NAMES utf8mb4;
SET @HEZHEN_OLD_SQL_MODE = @@SESSION.sql_mode;
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,NO_BACKSLASH_ESCAPES';
CREATE DATABASE IF NOT EXISTS hezhen_db CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE hezhen_db;
"""]
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip() + ";")
        # MySQL does not support CREATE INDEX IF NOT EXISTS; embed indexes into CREATE TABLE.
        indexes = [str(CreateIndex(index).compile(dialect=dialect)) for index in sorted(table.indexes, key=lambda index: index.name)]
        if indexes:
            ddl = parts.pop()
            additions = []
            for statement in indexes:
                name_and_columns = statement.split(" ON ", 1)
                name = name_and_columns[0].replace("CREATE INDEX ", "")
                columns = name_and_columns[1].split(" ", 1)[1]
                additions.append(f"INDEX {name} {columns}")
            at = ddl.rfind("\n)")
            parts.append(ddl[:at] + ",\n\t" + ",\n\t".join(additions) + ddl[at:])
    parts.append("\n-- 初始作物、38 个模型标签与已有知识条目；通过自然键定位外键，不覆盖已存在内容。\nSTART TRANSACTION;")
    crops, diseases, knowledge = seed_rows()
    crop_keys = {row["id"]: row["crop_key"] for row in crops}
    disease_labels = {row["id"]: row["model_label"] for row in diseases}
    for row in crops:
        row = {k: v for k, v in row.items() if k != "id"}
        values = ", ".join(literal(v) for v in row.values())
        parts.append(f"INSERT INTO crops ({', '.join(row)}) SELECT {values} WHERE NOT EXISTS (SELECT 1 FROM crops WHERE crop_key = {literal(row['crop_key'])});")
    for row in diseases:
        row = {k: v for k, v in row.items() if k != "id"}
        crop = crop_keys[row["crop_id"]]
        values = [f"(SELECT id FROM crops WHERE crop_key = {literal(crop)})" if k == "crop_id" else literal(v) for k, v in row.items()]
        parts.append(f"INSERT INTO diseases ({', '.join(row)}) SELECT {', '.join(values)} WHERE NOT EXISTS (SELECT 1 FROM diseases WHERE model_label = {literal(row['model_label'])});")
    for row in knowledge:
        label = disease_labels[row["disease_id"]]
        values = [f"(SELECT id FROM diseases WHERE model_label = {literal(label)})" if k == "disease_id" else literal(v) for k, v in row.items()]
        parts.append(f"INSERT INTO knowledge_base ({', '.join(row)}) SELECT {', '.join(values)} WHERE NOT EXISTS (SELECT 1 FROM knowledge_base WHERE source_code = {literal(row['source_code'])});")
    parts.append("COMMIT;\nSET SESSION sql_mode = @HEZHEN_OLD_SQL_MODE;\n")
    return "\n".join(line.rstrip() for line in "\n\n".join(parts).splitlines()) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "sql" / "禾诊_MySQL初始化.sql"
    target.parent.mkdir(exist_ok=True)
    target.write_text(build_sql(), encoding="utf-8")
    print(f"Generated {target.name}")
