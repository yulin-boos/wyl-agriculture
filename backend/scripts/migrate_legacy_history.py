"""Copy legacy diagnosis_records into the configured six-table database; never delete source rows."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, text
from app.database import SessionLocal, engine, check_schema
from app.models import DiagnosisRecord, Disease


def migrate(source_engine):
    check_schema()
    with source_engine.connect() as source:
        rows = source.execute(text("SELECT * FROM diagnosis_records")).mappings().all()
    copied = 0
    with SessionLocal.begin() as target:
        for row in rows:
            if target.get(DiagnosisRecord, row["id"]):
                continue
            disease = target.scalar(select(Disease).where(Disease.model_label == row["model_label"]))
            if disease is None or not row["client_id"]:
                raise ValueError(f"Cannot migrate record {row['id']}: missing model label or client ID")
            values = {key: row[key] for key in DiagnosisRecord.__table__.columns.keys()
                      if key in row and key not in {"crop_id", "disease_id", "user_id"}}
            for key in ("diagnosis_json", "advice_json"):
                if isinstance(values[key], str):
                    values[key] = json.loads(values[key])
            if isinstance(values.get("created_at"), str):
                values["created_at"] = datetime.fromisoformat(values["created_at"])
            target.add(DiagnosisRecord(**values, crop_id=disease.crop_id, disease_id=disease.id))
            copied += 1
    return copied


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, help="Legacy web.db; omit to copy diagnosis_records in the target database")
    arguments = parser.parse_args()
    if arguments.sqlite and not arguments.sqlite.is_file():
        raise SystemExit("Legacy SQLite file does not exist.")
    source = create_engine(f"sqlite:///{arguments.sqlite.resolve().as_posix()}") if arguments.sqlite else engine
    print(f"Migrated {migrate(source)} records. Source data retained.")
