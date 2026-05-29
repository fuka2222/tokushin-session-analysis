#!/usr/bin/env python3
"""ロスターTSVのセッション日付列(0-8)から頻度を集計。"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
SESSION_COLS = [str(i) for i in range(9)]  # 0..8


def parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s or "1900" in s:
        return None
    s = s.replace("-", "/")
    for fmt in ("%Y/%m/%d", "%Y/%-m/%-d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def intervals_days(dates: list[datetime]) -> list[int]:
    if len(dates) < 2:
        return []
    return [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]


def classify_pace(median_gap: float | None) -> str:
    if median_gap is None:
        return "—"
    if median_gap <= 9:
        return "ほぼ毎週"
    if median_gap <= 16:
        return "隔週寄り"
    return "月1寄り"


def main() -> None:
    path = ROOT / "data" / "metadata" / "roster_paste.tsv"
    rows = list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))

    results = []
    weekly_8 = []

    for row in rows:
        name = row.get("生徒名", "").strip()
        if not name or name.startswith("【重複】") or "テスト" in name:
            continue
        mg = row.get("担当MG名", "").strip()
        first = parse_date(row.get("1回目通常セッション", ""))

        dates = []
        for col in SESSION_COLS:
            d = parse_date(row.get(col, ""))
            if d:
                dates.append(d)
        dates = sorted(set(dates))

        gaps = intervals_days(dates)
        med = median(gaps) if gaps else None
        n = len(dates)

        # 8回以上 & 中央間隔が10日以内 ≒ 週1ペースで8回組めている
        is_weekly_8 = n >= 8 and med is not None and med <= 10

        results.append(
            {
                "name": name,
                "mg": mg,
                "n_scheduled": n,
                "median_gap_days": round(med, 1) if med else None,
                "pace": classify_pace(med),
                "first_session": first.strftime("%Y-%m-%d") if first else "",
                "dates": [d.strftime("%m/%d") for d in dates],
            }
        )
        if is_weekly_8:
            weekly_8.append(name)

    results.sort(key=lambda x: (-x["n_scheduled"], x["name"]))

    print("=== 虎の巻の想定ペース（参考）===")
    print("伴走11回: 初月は毎週(約3〜4回) → 隔週 → 月1")
    print()

    print("=== ロスター上の予定日数（列0〜8に日付がある数）===")
    print(f"{'生徒名':<16} {'MG':<10} {'予定数':>4} {'間隔(日)':>8} {'ペース':<10} 日付")
    for r in results:
        if r["n_scheduled"] == 0:
            continue
        gap = r["median_gap_days"] if r["median_gap_days"] else "—"
        print(
            f"{r['name']:<16} {r['mg']:<10} {r['n_scheduled']:>4} {str(gap):>8} "
            f"{r['pace']:<10} {' → '.join(r['dates'])}"
        )

    print()
    print(f"予定が8回以上入っている人: {sum(1 for r in results if r['n_scheduled']>=8)}名")
    print(f"そのうち間隔中央値≤10日（ほぼ週1×8）: {len(weekly_8)}名")
    if weekly_8:
        print("  →", ", ".join(weekly_8))
    else:
        print("  → 該当者なし（8回分あっても隔週以降に切り替わっている人が多い）")

    dist = {}
    for r in results:
        if r["n_scheduled"] > 0:
            dist[r["n_scheduled"]] = dist.get(r["n_scheduled"], 0) + 1
    print()
    print("予定回数の分布:", dict(sorted(dist.items())))


if __name__ == "__main__":
    main()
