#!/usr/bin/env python3
"""SQLite → スプレッドシート用マスタCSVを出力。"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER_DIR = ROOT / "data" / "master"
DB_PATH = MASTER_DIR / "session_analysis.db"

from db import HEARING_KEYS, connect  # noqa: E402


def export_sessions(conn: sqlite3.Connection) -> Path:
    out = MASTER_DIR / "sessions_evaluations.csv"
    rows = conn.execute(
        """
        SELECT student_id, mg_name, session_number, session_date, sp_start_date,
               days_from_sp_start, evaluated_at, evaluation_method,
               structure_adherence_rate, script_delivery_likelihood,
               missing_blocks, partial_blocks, structure_comment,
               transcript_source, result_json_path
        FROM session_evaluations
        ORDER BY evaluated_at DESC, student_id, session_number
        """
    ).fetchall()

    headers = [
        "student_id",
        "mg_name",
        "session_number",
        "session_date",
        "sp_start_date",
        "days_from_sp_start",
        "evaluated_at",
        "evaluation_method",
        "structure_adherence_rate",
        "script_delivery_likelihood",
        "missing_blocks",
        "partial_blocks",
        "structure_comment",
        "transcript_source",
        "result_json_path",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow([r[h] for h in headers])
    return out


def export_hearing_wide(conn: sqlite3.Connection) -> Path:
    """ヒアリング項目を横持ち1行に（スプレッドシート向け）。"""
    out = MASTER_DIR / "hearing_wide.csv"
    evals = conn.execute(
        "SELECT student_id, session_number, mg_name, evaluated_at FROM session_evaluations ORDER BY student_id, session_number"
    ).fetchall()

    hearing_rows: dict[tuple, dict] = {}
    for r in conn.execute(
        "SELECT student_id, session_number, field_key, value, confidence FROM hearing_fields"
    ):
        key = (r["student_id"], r["session_number"])
        hearing_rows.setdefault(key, {})[r["field_key"]] = r["value"]
        hearing_rows[key][f"{r['field_key']}_confidence"] = r["confidence"]

    headers = ["student_id", "session_number", "mg_name", "evaluated_at"]
    for k in HEARING_KEYS:
        headers.extend([k, f"{k}_confidence"])

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for ev in evals:
            key = (ev["student_id"], ev["session_number"])
            h = hearing_rows.get(key, {})
            row = [ev["student_id"], ev["session_number"], ev["mg_name"], ev["evaluated_at"]]
            for k in HEARING_KEYS:
                row.append(h.get(k, ""))
                row.append(h.get(f"{k}_confidence", ""))
            w.writerow(row)
    return out


def export_mg_summary(conn: sqlite3.Connection, session_filter: int = 1) -> Path:
    out = MASTER_DIR / "mg_adherence_summary.csv"
    rows = conn.execute(
        """
        SELECT mg_name,
               COUNT(*) AS session_count,
               ROUND(AVG(structure_adherence_rate), 3) AS adherence_mean,
               ROUND(AVG(CASE WHEN script_delivery_likelihood='high' THEN 1.0 ELSE 0.0 END), 3) AS high_likelihood_rate
        FROM session_evaluations
        WHERE session_number = ?
        GROUP BY mg_name
        ORDER BY adherence_mean DESC
        """,
        (session_filter,),
    ).fetchall()

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mg_name", "session_count", "adherence_mean", "high_likelihood_rate"])
        for r in rows:
            w.writerow([r["mg_name"], r["session_count"], r["adherence_mean"], r["high_likelihood_rate"]])
    return out


def export_daily_log(conn: sqlite3.Connection) -> Path:
    out = MASTER_DIR / "daily_evaluation_counts.csv"
    rows = conn.execute(
        """
        SELECT date(evaluated_at) AS eval_date,
               COUNT(*) AS count,
               ROUND(AVG(structure_adherence_rate), 3) AS avg_adherence
        FROM session_evaluations
        GROUP BY date(evaluated_at)
        ORDER BY eval_date DESC
        """
    ).fetchall()

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eval_date", "count", "avg_adherence"])
        for r in rows:
            w.writerow([r["eval_date"], r["count"], r["avg_adherence"]])
    return out


def export_all(db_path: Path | None = None) -> list[Path]:
    conn = connect(db_path)
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        export_sessions(conn),
        export_hearing_wide(conn),
        export_mg_summary(conn),
        export_daily_log(conn),
    ]
    conn.close()
    return paths


def main() -> None:
    paths = export_all()
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
