#!/usr/bin/env python3
"""
コミットプラン「セッション実施状況管理」シートから、指定コホートの集計を行う。

集計内容:
  1. MG別：通常コーチング（W列=0回目〜）のセッション間隔が毎週ペース（5〜9日）の割合
  2. SP開始日 → 自己分析セッション実施日（V列）の日数差

用法:
  python scripts/analyze_commit_plan_cohort.py "/path/to/コミットプラン (N).xlsx"
  python scripts/analyze_commit_plan_cohort.py --year 2026 --month 4
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

HEADER_ROW = 9
DATA_START = 10

COL = {
    "no": 0,
    "status": 1,
    "name": 7,
    "enroll": 13,
    "lecture": 14,
    "interview": 15,
    "sp_start": 16,
    "first_regular": 18,  # 1回目通常セッション（旧レイアウトでは17=SPタイプ）
    "mg": 20,  # 担当MG名（旧レイアウトでは19=最終サポート日）
}
# コミットプラン(9)+: 列22=自己分析（行9ヘッダは「0」）、列23〜=通常コーチング1〜12
SELF_ANALYSIS_COL = 22
COACHING_COLS = list(range(23, 35))

WEEKLY_MIN, WEEKLY_MAX = 5, 9

_DATE_IN_MG = re.compile(r"20\d{2}[/\-]|00:00:00")


def normalize_mg(raw) -> str:
    """担当MG名（U列=col20）。日付・最終サポート日の誤混入を除外。"""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    if isinstance(raw, datetime):
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return ""
    if _DATE_IN_MG.search(s):
        return ""
    return s


def parse_date(v) -> datetime.date | None:
    if isinstance(v, datetime):
        d = v.date()
        return d if 2020 <= d.year <= 2030 else None
    if pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s in ("-", "nan"):
        return None
    skip = ("停止", "解約", "音不", "受講開始", "#REF", "#VALUE", "不明")
    if any(x in s for x in skip):
        return None
    try:
        dt = pd.to_datetime(v, errors="coerce")
        if pd.isna(dt) or dt.year < 2020 or dt.year == 1900:
            return None
        return dt.date()
    except Exception:
        return None


def is_valid_name(name) -> bool:
    if pd.isna(name):
        return False
    s = str(name).strip()
    return bool(s) and not s.startswith("以下") and "テスト" not in s and "【" not in s


def cohort_date_in_month(row, year: int, month: int) -> bool:
    for c in (COL["enroll"], COL["lecture"], COL["interview"], COL["sp_start"]):
        d = parse_date(row[c])
        if d and d.year == year and d.month == month:
            return True
    sa = parse_date(row[SELF_ANALYSIS_COL])
    if sa and sa.year == year and sa.month == month:
        return True
    return False


def get_coaching_dates(row) -> list:
    dates = [parse_date(row[c]) for c in COACHING_COLS]
    return sorted(d for d in dates if d)


def weekly_stats(dates: list) -> dict:
    if len(dates) < 2:
        return {
            "n_intervals": 0,
            "weekly_intervals": 0,
            "gaps": [],
            "all_weekly": None,
            "mostly_weekly": None,
        }
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    weekly = sum(1 for g in gaps if WEEKLY_MIN <= g <= WEEKLY_MAX)
    return {
        "n_intervals": len(gaps),
        "weekly_intervals": weekly,
        "gaps": gaps,
        "all_weekly": all(WEEKLY_MIN <= g <= WEEKLY_MAX for g in gaps),
        "mostly_weekly": weekly / len(gaps) >= 0.8,
    }


def find_tokushin_start(df: pd.DataFrame) -> int | None:
    for i in range(len(df)):
        v = df.iloc[i, COL["name"]]
        if pd.notna(v) and "新特進" in str(v):
            return i
    return None


def load_students(df: pd.DataFrame, year: int, month: int, tokushin_only: bool) -> list[dict]:
    tokushin_row = find_tokushin_start(df)
    start = (tokushin_row + 1) if (tokushin_only and tokushin_row is not None) else DATA_START

    students = []
    for i in range(start, len(df)):
        row = df.iloc[i]
        if not is_valid_name(row[COL["name"]]):
            # 「以下、自己分析セッションあり」等の小見出しはスキップのみ（以降も新特進生徒が続く）
            continue
        if not cohort_date_in_month(row, year, month):
            continue

        mg = normalize_mg(row[COL["mg"]])

        sp = parse_date(row[COL["sp_start"]])
        sa = parse_date(row[SELF_ANALYSIS_COL])
        coaching = get_coaching_dates(row)
        ws = weekly_stats(coaching)

        students.append(
            {
                "name": str(row[COL["name"]]).strip(),
                "mg": mg,
                "status": row[COL["status"]],
                "sp": sp,
                "self_analysis": sa,
                "sa_gap": (sa - sp).days if sa and sp else None,
                "coaching_dates": coaching,
                "n_coaching": len(coaching),
                **ws,
            }
        )

    # dedupe by name: prefer MG filled, more sessions
    by_name: dict[str, dict] = {}
    for s in students:
        key = s["name"].replace("　", " ").lower()
        score = (1 if s["mg"] else 0, s["n_coaching"], 1 if s["sp"] else 0)
        if key not in by_name:
            by_name[key] = s
        else:
            old = by_name[key]
            old_score = (1 if old["mg"] else 0, old["n_coaching"], 1 if old["sp"] else 0)
            if score > old_score:
                by_name[key] = s
    return list(by_name.values())


def print_self_analysis_report(students: list[dict]) -> None:
    with_sa = [s for s in students if s["self_analysis"]]
    with_sp = [s for s in students if s["sa_gap"] is not None]

    print("\n=== 自己分析セッション：SP開始日 → V列（自己分析実施日）===")
    print(f"自己分析日あり: {len(with_sa)}名 / SP開始日入力済: {len(with_sp)}名")

    if with_sp:
        gaps = [s["sa_gap"] for s in with_sp]
        import numpy as np

        arr = np.array(gaps)
        print(f"  平均 {arr.mean():.1f}日 / 中央値 {np.median(arr):.0f}日 / 範囲 {arr.min()}〜{arr.max()}日")
        print(f"  25/75%ile: {np.percentile(arr, 25):.0f} / {np.percentile(arr, 75):.0f}日")
        for lo, hi, label in [
            (0, 3, "0〜3日"),
            (4, 7, "4〜7日"),
            (8, 14, "8〜14日"),
            (15, 21, "15〜21日"),
            (22, 999, "22日以上"),
        ]:
            n = sum(1 for g in gaps if lo <= g <= hi)
            print(f"  {label}: {n}名 ({n / len(gaps) * 100:.0f}%)")

    if len(with_sp) < len(with_sa):
        missing = len(with_sa) - len(with_sp)
        print(f"\n※ SP開始日（Q列）未入力: {missing}名 — 最新ExcelでQ列入力後に再実行してください")


def print_weekly_report(students: list[dict]) -> None:
    print("\n=== 通常コーチング間隔（W列=0回目〜）===")
    print(f"毎週ペース = 隣接セッション間隔 {WEEKLY_MIN}〜{WEEKLY_MAX}日\n")

    mg = defaultdict(lambda: {"students": 0, "with2": 0, "all_w": 0, "mostly_w": 0, "ti": 0, "wi": 0})
    for s in students:
        m = s["mg"] or "(MG未入力)"
        mg[m]["students"] += 1
        if s["n_coaching"] >= 2:
            mg[m]["with2"] += 1
            if s["all_weekly"]:
                mg[m]["all_w"] += 1
            if s["mostly_weekly"]:
                mg[m]["mostly_w"] += 1
            mg[m]["ti"] += s["n_intervals"]
            mg[m]["wi"] += s["weekly_intervals"]

    print(f"{'MG':<12} {'生徒':>4} {'判定可':>5} {'全間隔OK':>7} {'80%OK':>6} {'生徒達成率':>9} {'間隔達成率':>9}")
    print("-" * 66)
    totals = dict(s=0, w2=0, aw=0, mw=0, ti=0, wi=0)
    for m in sorted(mg, key=lambda x: (-mg[x]["students"], x)):
        d = mg[m]
        sr = f"{d['all_w'] / d['with2'] * 100:.0f}%" if d["with2"] else "-"
        ir = f"{d['wi'] / d['ti'] * 100:.0f}%" if d["ti"] else "-"
        print(
            f"{m:<12} {d['students']:>4} {d['with2']:>5} {d['all_w']:>7} {d['mostly_w']:>6} {sr:>9} {ir:>9}"
        )
        for k, kk in [("s", "students"), ("w2", "with2"), ("aw", "all_w"), ("mw", "mostly_w"), ("ti", "ti"), ("wi", "wi")]:
            totals[k] += d[kk]

    print("-" * 66)
    if totals["w2"]:
        print(
            f"{'合計':<12} {totals['s']:>4} {totals['w2']:>5} {totals['aw']:>7} {totals['mw']:>6} "
            f"{totals['aw'] / totals['w2'] * 100:.0f}%{'':>4} {totals['wi'] / totals['ti'] * 100:.0f}%"
        )

    insuf = sum(1 for s in students if s["n_coaching"] < 2)
    print(f"\nコーチング2回未満で判定不可: {insuf}名")


def main() -> int:
    parser = argparse.ArgumentParser(description="コミットプラン セッション実施状況 コホート集計")
    parser.add_argument("xlsx", type=Path, help="コミットプラン xlsx パス")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=4, help="入会コホートの月（SP/講義/面談/自己分析のいずれか）")
    parser.add_argument("--all-students", action="store_true", help="新特進ブロック以外も含める")
    args = parser.parse_args()

    if not args.xlsx.exists():
        print(f"File not found: {args.xlsx}", file=sys.stderr)
        return 1

    df = pd.read_excel(args.xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, args.year, args.month, tokushin_only=not args.all_students)

    scope = "全生徒" if args.all_students else "新特進"
    print(f"対象: {args.year}年{args.month}月入会（{scope}）— {len(students)}名")
    print(f"データ: {args.xlsx.name}")

    print_self_analysis_report(students)
    print_weekly_report(students)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
