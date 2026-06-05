#!/usr/bin/env python3
"""sp_start_dates.tsv → roster_paste.tsv の SP開始日 列を更新する。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sp_start_lookup import format_roster, load_sp_start_index, names_match  # noqa: E402

ROSTER = ROOT / "data/metadata/roster_paste.tsv"
SP_PATH = ROOT / "data/metadata/sp_start_dates.tsv"


def main() -> None:
    index = load_sp_start_index(SP_PATH)
    rows: list[dict] = []
    with ROSTER.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames or []
        for row in reader:
            name = (row.get("生徒名") or "").strip()
            if not name or name.startswith("【"):
                rows.append(row)
                continue
            matched = None
            for sp_name, d in index.items():
                if names_match(name, sp_name):
                    matched = d
                    break
            if matched:
                old = (row.get("SP開始日") or "").strip()
                new = format_roster(matched)
                row["SP開始日"] = new
                if old != new:
                    print(f"  {name}: {old or '(空)'} → {new}")
            rows.append(row)

    with ROSTER.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"Updated {ROSTER}")


if __name__ == "__main__":
    main()
