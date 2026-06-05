#!/usr/bin/env python3
"""講師1on1貼付（To, 1〜5回目, 担当MG, 講師名）をTSVに保存"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

SESSION_COLS = ["1回目", "2回目", "3回目", "4回目", "5回目"]
OUT_COLS = ["To", *SESSION_COLS, "担当MG", "講師名"]


def parse_paste(text: str) -> pd.DataFrame:
    m = re.search(r"To\t1回目.*", text, re.DOTALL)
    if not m:
        raise ValueError("貼付にヘッダ行 To\\t1回目 が見つかりません")
    rows = []
    for line in m.group(0).splitlines():
        if not line.strip() or line.startswith("To\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name = parts[0].strip()
        if not name:
            continue
        flags = [p.strip().upper() for p in parts[1:6]]
        mg = parts[6].strip() if len(parts) > 6 else ""
        teacher = parts[7].strip() if len(parts) > 7 else ""
        rows.append(
            {
                "To": name,
                **{SESSION_COLS[i]: ("TRUE" if flags[i] in ("TRUE", "1", "1.0") else "FALSE") for i in range(5)},
                "担当MG": mg,
                "講師名": teacher,
            }
        )
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["To"], keep="last")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paste_file", type=Path, help="貼付全文を保存したテキストファイル")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "metadata" / "instructor_1on1_latest.tsv",
    )
    args = parser.parse_args()
    text = args.paste_file.read_text(encoding="utf-8")
    df = parse_paste(text)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df[OUT_COLS].to_csv(args.out, sep="\t", index=False)
    print(f"saved {len(df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
