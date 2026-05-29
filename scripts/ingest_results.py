#!/usr/bin/env python3
"""data/results/*.json をSQLiteに取り込み、マスタCSVを更新する。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect, ingest_json_file  # noqa: E402
from export_master import export_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="評価JSONをDBに蓄積")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "data" / "results",
    )
    parser.add_argument("--pattern", default="*.json", help="例: *_manual.json")
    parser.add_argument("--no-export", action="store_true", help="CSVエクスポートをスキップ")
    args = parser.parse_args()

    files = sorted(args.results_dir.glob(args.pattern))
    if not files:
        print(f"対象なし: {args.results_dir / args.pattern}")
        return

    conn = connect()
    stats = {"inserted": 0, "updated": 0, "error": 0}

    for path in files:
        if path.name.startswith("."):
            continue
        try:
            status = ingest_json_file(conn, path)
            stats[status] += 1
            print(f"{status}: {path.name}")
        except Exception as e:
            stats["error"] += 1
            print(f"error: {path.name} — {e}")

    conn.close()
    print(f"\n完了 — 新規:{stats['inserted']} 更新:{stats['updated']} エラー:{stats['error']}")

    if not args.no_export:
        paths = export_all()
        print("エクスポート:")
        for p in paths:
            print(f"  {p}")
        try:
            from build_dashboard import build

            print(f"  {build()}")
        except Exception as e:
            print(f"ダッシュボード生成スキップ: {e}")


if __name__ == "__main__":
    main()
