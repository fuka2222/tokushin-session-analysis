#!/usr/bin/env python3
"""
日次バッチ: 未処理の文字起こしを最大N件評価 → JSON保存 → DB蓄積 → CSVエクスポート。

使い方:
  python scripts/daily_run.py              # デフォルト10件
  python scripts/daily_run.py --limit 5
  python scripts/daily_run.py --ingest-only  # 既存JSONのみ取り込み
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from batch_evaluate import FNAME_RE, load_metadata, parse_filename  # noqa: E402
from db import connect, ingest_json_file  # noqa: E402
from evaluate_session import evaluate  # noqa: E402
from export_master import export_all  # noqa: E402

INBOX = ROOT / "data" / "inbox"
PROCESSED = ROOT / "data" / "transcripts"
RESULTS = ROOT / "data" / "results"
LOG_DIR = ROOT / "data" / "logs"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"daily_{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("daily_run")


def collect_pending(limit: int, inbox_only: bool) -> list[Path]:
    """未評価の文字起こしファイルを収集。"""
    dirs = [INBOX] if inbox_only else [INBOX, PROCESSED]
    pending: list[Path] = []

    for d in dirs:
        if not d.exists():
            continue
        for ext in ("*.vtt", "*.txt"):
            for path in sorted(d.glob(ext)):
                parsed = parse_filename(path)
                if not parsed:
                    continue
                out = RESULTS / f"{parsed['student_id']}_{parsed['session_number']}.json"
                if not out.exists():
                    pending.append(path)

    return pending[:limit]


def run_evaluations(
    logger: logging.Logger,
    limit: int,
    metadata_path: Path,
    delay_sec: float,
    skip_hearing: bool,
    move_inbox: bool,
) -> dict:
    meta = load_metadata(metadata_path)
    pending = collect_pending(limit, inbox_only=False)
    stats = {"ok": 0, "fail": 0, "skipped": 0}

    if not pending:
        logger.info("未処理の文字起こしはありません")
        return stats

    logger.info("処理対象 %d 件（上限 %d）", len(pending), limit)

    for i, path in enumerate(pending):
        parsed = parse_filename(path)
        if not parsed:
            stats["skipped"] += 1
            continue

        sid = parsed["student_id"]
        sn = parsed["session_number"]
        out = RESULTS / f"{sid}_{sn}.json"
        row = meta.get((sid, sn), {})
        mg = row.get("mg_name") or parsed["mg_name"]

        logger.info("[%d/%d] 評価開始: %s", i + 1, len(pending), path.name)
        try:
            result = evaluate(
                path,
                sn,
                sid,
                mg,
                sp_start_date=row.get("sp_start_date", ""),
                session_date=row.get("session_date", ""),
                step_at_assign=row.get("step_at_assign", ""),
                skip_hearing=skip_hearing,
            )
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("  保存: %s 遵守率=%s", out.name, result["structure"].get("structure_adherence_rate"))
            stats["ok"] += 1

            if path.parent == INBOX and move_inbox:
                dest = PROCESSED / path.name
                shutil.move(str(path), str(dest))
                logger.info("  移動: inbox → transcripts/%s", path.name)

        except Exception as e:
            logger.error("  失敗: %s", e)
            stats["fail"] += 1

        if i < len(pending) - 1 and delay_sec > 0:
            time.sleep(delay_sec)

    return stats


def ingest_all_results(logger: logging.Logger) -> dict:
    conn = connect()
    stats = {"inserted": 0, "updated": 0, "error": 0}

    for path in sorted(RESULTS.glob("*.json")):
        try:
            status = ingest_json_file(conn, path)
            stats[status] += 1
        except Exception as e:
            stats["error"] += 1
            logger.error("ingest失敗 %s: %s", path.name, e)

    conn.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="日次セッション分析バッチ")
    parser.add_argument("--limit", type=int, default=10, help="1日の評価上限（デフォルト10）")
    parser.add_argument("--delay", type=float, default=2.0, help="API呼び出し間隔（秒）")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data" / "metadata" / "sessions.csv")
    parser.add_argument("--skip-hearing", action="store_true")
    parser.add_argument("--no-move", action="store_true", help="inboxからtranscriptsへ移動しない")
    parser.add_argument("--ingest-only", action="store_true", help="評価せずJSON取り込みのみ")
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("=== daily_run 開始 ===")

    INBOX.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    if not args.ingest_only:
        eval_stats = run_evaluations(
            logger,
            args.limit,
            args.metadata,
            args.delay,
            args.skip_hearing,
            move_inbox=not args.no_move,
        )
        logger.info("評価結果: %s", eval_stats)

    ingest_stats = ingest_all_results(logger)
    logger.info("DB取り込み: %s", ingest_stats)

    if not args.no_export:
        paths = export_all()
        logger.info("CSVエクスポート完了:")
        for p in paths:
            logger.info("  %s", p)

    try:
        from build_dashboard import build

        dash = build()
        logger.info("ダッシュボード更新: %s", dash)
    except Exception as e:
        logger.error("ダッシュボード生成失敗: %s", e)

    logger.info("=== daily_run 終了 ===")


if __name__ == "__main__":
    main()
