"""セッション評価結果のSQLite蓄積。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "master" / "session_analysis.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    mg_name TEXT,
    session_number INTEGER NOT NULL,
    session_date TEXT,
    sp_start_date TEXT,
    days_from_sp_start INTEGER,
    evaluated_at TEXT NOT NULL,
    evaluation_method TEXT,
    structure_adherence_rate REAL,
    script_delivery_likelihood TEXT,
    missing_blocks TEXT,
    partial_blocks TEXT,
    structure_comment TEXT,
    transcript_source TEXT,
    result_json_path TEXT,
    UNIQUE(student_id, session_number)
);

CREATE TABLE IF NOT EXISTS hearing_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_number INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT,
    confidence TEXT,
    evidence TEXT,
    evaluated_at TEXT NOT NULL,
    UNIQUE(student_id, session_number, field_key)
);

CREATE INDEX IF NOT EXISTS idx_eval_mg ON session_evaluations(mg_name);
CREATE INDEX IF NOT EXISTS idx_eval_date ON session_evaluations(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_hearing_student ON hearing_fields(student_id, session_number);
"""

def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


HEARING_KEYS = [
    "family_structure",
    "genre",
    "age",
    "occupation",
    "computer_literacy",
    "session1_satisfaction",
    "join_motivation",
    "step_at_session",
    "step_at_assign",
    "time_before_coach",
    "work_time_availability",
    "time_change_before_after",
    "step_progress_before_session",
    "step_progress_after_session",
]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _join_list(items: Any) -> str:
    if not items:
        return ""
    if isinstance(items, list):
        return ",".join(str(x) for x in items)
    return str(items)


def parse_result_payload(data: dict) -> tuple[dict, dict]:
    """JSONペイロードを structure / hearing に正規化。"""
    structure = data.get("structure") or data
    hearing = data.get("hearing") or {}
    meta = data.get("meta") or {}

    if "structure_adherence_rate" in data and "blocks" not in data:
        structure = data

    return structure, hearing, meta


def ingest_json_file(conn: sqlite3.Connection, json_path: Path) -> str:
    """
    1件の結果JSONをDBへ upsert。
    Returns: 'inserted' | 'updated' | 'skipped'
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    structure, hearing, meta = parse_result_payload(data)

    student_id = structure.get("student_id") or meta.get("student_id")
    session_number = structure.get("session_number")
    if not student_id or session_number is None:
        raise ValueError(f"student_id / session_number が不明: {json_path}")

    mg_name = structure.get("mg_name") or meta.get("mg_name")
    evaluated_at = (
        meta.get("evaluated_at")
        or structure.get("evaluated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    method = meta.get("method") or meta.get("evaluation_method") or "gemini"

    days = hearing.get("days_from_sp_start")
    if days is None and isinstance(hearing.get("days_from_sp_start"), dict):
        days = hearing["days_from_sp_start"].get("value")

    row = {
        "student_id": student_id,
        "mg_name": mg_name,
        "session_number": int(session_number),
        "session_date": structure.get("session_date") or meta.get("session_date"),
        "sp_start_date": meta.get("sp_start_date") or structure.get("sp_start_date"),
        "days_from_sp_start": days if days is not None else None,
        "evaluated_at": evaluated_at,
        "evaluation_method": method,
        "structure_adherence_rate": structure.get("structure_adherence_rate"),
        "script_delivery_likelihood": structure.get("script_delivery_likelihood"),
        "missing_blocks": _join_list(structure.get("missing_blocks")),
        "partial_blocks": _join_list(structure.get("partial_blocks")),
        "structure_comment": structure.get("structure_adherence_comment"),
        "transcript_source": meta.get("transcript_path") or meta.get("source"),
        "result_json_path": _relative_path(json_path, ROOT),
    }

    cur = conn.execute(
        "SELECT id FROM session_evaluations WHERE student_id=? AND session_number=?",
        (student_id, session_number),
    )
    exists = cur.fetchone()

    cols = list(row.keys())
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("student_id", "session_number"))

    conn.execute(
        f"""
        INSERT INTO session_evaluations ({",".join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(student_id, session_number) DO UPDATE SET {updates}
        """,
        tuple(row[c] for c in cols),
    )

    for key in HEARING_KEYS:
        field = hearing.get(key)
        if field is None:
            continue
        if isinstance(field, dict):
            value = field.get("value")
            confidence = field.get("confidence")
            evidence = field.get("evidence")
        else:
            value, confidence, evidence = field, "high", ""

        conn.execute(
            """
            INSERT INTO hearing_fields
            (student_id, session_number, field_key, value, confidence, evidence, evaluated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, session_number, field_key) DO UPDATE SET
                value=excluded.value,
                confidence=excluded.confidence,
                evidence=excluded.evidence,
                evaluated_at=excluded.evaluated_at
            """,
            (
                student_id,
                int(session_number),
                key,
                str(value) if value is not None else None,
                confidence,
                evidence,
                evaluated_at,
            ),
        )

    conn.commit()
    return "updated" if exists else "inserted"
