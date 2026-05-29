#!/usr/bin/env python3
"""Lステップ xlsx → 貼付更新用 TSV を書き出す。"""
from __future__ import annotations

import argparse
from pathlib import Path

from lstep_sp_lookup import export_lstep_tsv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = Path.home() / "Downloads" / "Lステップの顧客データ (1).xlsx"
DEFAULT_OUT = ROOT / "data/metadata/lstep_tokushin.tsv"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("xlsx", nargs="?", type=Path, default=DEFAULT_XLSX)
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()
    if not args.xlsx.exists():
        raise SystemExit(f"Not found: {args.xlsx}")
    out = export_lstep_tsv(args.xlsx, args.output)
    print(f"Exported {out}")


if __name__ == "__main__":
    main()
