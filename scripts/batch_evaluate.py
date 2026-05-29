#!/usr/bin/env python3
"""data/transcripts 内のVTT/txtを一括評価する。"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_session import evaluate  # noqa: E402

# 推奨: S001_山田_1.vtt
FNAME_RE = re.compile(
    r"^(?P<student_id>[^_]+)_(?P<mg_name>[^_]+)_(?P<session>\d+)\.(vtt|txt)$",
    re.IGNORECASE,
)


def load_metadata(path: Path) -> dict[tuple[str, int], dict]:
    """sessions.csv: student_id, session_number, mg_name, ..."""
    if not path.exists():
        return {}
    rows: dict[tuple[str, int], dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["student_id"], int(row["session_number"]))
            rows[key] = row
    return rows


def parse_filename(path: Path) -> dict | None:
    m = FNAME_RE.match(path.name)
    if not m:
        return None
    return {
        "student_id": m.group("student_id"),
        "mg_name": m.group("mg_name"),
        "session_number": int(m.group("session")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "data" / "transcripts",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ROOT / "data" / "metadata" / "sessions.csv",
    )
    parser.add_argument("--skip-hearing", action="store_true")
    parser.add_argument("--force", action="store_true", help="既存結果を上書き")
    parser.add_argument("--limit", type=int, default=0, help="処理件数上限（0=無制限）")
    parser.add_argument("--delay", type=float, default=2.0, help="API呼び出し間隔（秒）")
    parser.add_argument("--sync-db", action="store_true", help="完了後にDB/CSVへ同期")
    args = parser.parse_args()

    meta = load_metadata(args.metadata)
    results_dir = ROOT / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(args.input_dir.glob("*.vtt")) + sorted(args.input_dir.glob("*.txt"))
    if not files:
        print(f"対象ファイルがありません: {args.input_dir}")
        sys.exit(1)

    if args.limit > 0:
        files = files[: args.limit]

    processed = 0
    for path in files:
        parsed = parse_filename(path)
        if not parsed:
            print(f"スキップ（命名規則不一致）: {path.name}")
            continue

        sid = parsed["student_id"]
        sn = parsed["session_number"]
        out = results_dir / f"{sid}_{sn}.json"
        if out.exists() and not args.force:
            print(f"スキップ（既存）: {out.name}")
            continue

        row = meta.get((sid, sn), {})
        mg = row.get("mg_name") or parsed["mg_name"]

        print(f"評価中: {path.name} ...")
        result = evaluate(
            path,
            sn,
            sid,
            mg,
            sp_start_date=row.get("sp_start_date", ""),
            session_date=row.get("session_date", ""),
            step_at_assign=row.get("step_at_assign", ""),
            skip_hearing=args.skip_hearing,
        )
        out.write_text(
            __import__("json").dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rate = result["structure"].get("structure_adherence_rate")
        print(f"  → {out.name} 遵守率={rate}")
        processed += 1
        if args.delay > 0 and processed < len(files):
            time.sleep(args.delay)

    if args.sync_db and processed > 0:
        from db import connect, ingest_json_file
        from export_master import export_all

        conn = connect()
        for json_path in sorted((ROOT / "data" / "results").glob("*.json")):
            ingest_json_file(conn, json_path)
        conn.close()
        export_all()
        print("DB/CSV同期完了")


if __name__ == "__main__":
    main()
