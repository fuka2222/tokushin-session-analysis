#!/usr/bin/env python3
"""4月コホートのうち、集計基準日時点で SP開始から30日以上経過した生徒のみで再集計。"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_commit_plan_cohort import load_students, weekly_stats
from lstep_sp_lookup import build_lstep_index, load_lstep_xlsx, norm_name

SP50_EXCLUDE = {
    norm_name(n)
    for n in [
        "あさのえりか",
        "あらき　りえこ",
        "あわやしょうま",
        "ふっくみな",
        "しまおかみさと",
    ]
}


def load_rows(
    xlsx: Path,
    lstep_tsv: Path,
    lstep_xlsx: Path | None,
    year: int,
    month: int,
    snapshot: date,
    min_days_since_sp: int,
) -> tuple[list[dict], list[dict]]:
    df = pd.read_excel(xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, year, month, tokushin_only=True)
    lstep_idx = build_lstep_index(lstep_tsv)
    if lstep_xlsx and lstep_xlsx.exists():
        for rec in load_lstep_xlsx(lstep_xlsx):
            lstep_idx[rec["norm_name"]] = rec

    all_rows: list[dict] = []
    for s in students:
        hit = lstep_idx.get(norm_name(s["name"]), {})
        sp = hit.get("sp_start") or s.get("sp")
        if not sp:
            continue
        sa = s.get("self_analysis")
        coach = s.get("coaching_dates") or []
        ws = weekly_stats(coach)
        sp_complete = hit.get("sp_complete")
        days_since = (snapshot - sp).days
        all_rows.append(
            {
                "name": s["name"],
                "mg": s.get("mg") or "",
                "sp": sp,
                "days_since_sp": days_since,
                "sa_gap": (sa - sp).days if sa else None,
                "sp_days": (sp_complete - sp).days if sp_complete else None,
                "step": hit.get("latest_step", 0) or 0,
                "n_coach": len(coach),
                "weekly_rate": (
                    ws["weekly_intervals"] / ws["n_intervals"] if ws["n_intervals"] else None
                ),
                "all_weekly": ws["all_weekly"],
                "coach_sp": (coach[0] - sp).days if coach else None,
                "sa_coach": (
                    (coach[0] - sa).days if sa and coach and coach[0] >= sa else None
                ),
                "sp50": norm_name(s["name"]) in SP50_EXCLUDE,
            }
        )

    excluded = [r for r in all_rows if r["days_since_sp"] < min_days_since_sp]
    included = [r for r in all_rows if r["days_since_sp"] >= min_days_since_sp]
    return included, excluded


def _median(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _corr(x: list, y: list) -> tuple[float | None, int]:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    return float(np.corrcoef(xs, ys)[0, 1]), len(pairs)


def print_report(rows: list[dict], excluded: list[dict], snapshot: date, min_days: int) -> None:
    total = len(rows)
    print(f"集計基準日: {snapshot}")
    print(f"母数: SP開始から{min_days}日以上 — {total}名")
    print(f"除外: {len(excluded)}名")
    for r in sorted(excluded, key=lambda x: x["days_since_sp"]):
        print(f"  - {r['name']}: SP開始{r['sp']} (+{r['days_since_sp']}日)")

    print("\n--- SA gap ---")
    for label, pred in [
        ("7日以内", lambda g: g <= 7),
        ("8-14日", lambda g: 8 <= g <= 14),
        ("15日超", lambda g: g >= 15),
    ]:
        grp = [r for r in rows if r["sa_gap"] is not None and pred(r["sa_gap"])]
        steps = [r["step"] for r in grp]
        print(
            f"{label}: {len(grp)}名 ({len(grp)/total*100:.1f}%) "
            f"STEP中央値={_median(steps)}"
        )

    print("\n--- SP完了（累積）---")
    for t in [15, 20, 25, 30, 35, 40, 45, 60]:
        grp = [r for r in rows if r["sp_days"] is not None and r["sp_days"] <= t]
        gaps = [r["sa_gap"] for r in grp if r["sa_gap"] is not None]
        sa7 = sum(1 for r in grp if r["sa_gap"] is not None and r["sa_gap"] <= 7)
        print(
            f"SP+{t}日以内: {len(grp)}/{total} ({len(grp)/total*100:.0f}%) "
            f"SA gap中央値={_median(gaps)} SA7日以内={sa7}/{len(grp) or 1}"
        )

    nd = [r for r in rows if r["sp_days"] is None]
    print(f"SP未完了: {len(nd)}名")

    print("\n--- 相関 ---")
    for a, b, x, y in [
        ("STEP", "SA gap", [r["step"] for r in rows], [r["sa_gap"] for r in rows]),
        ("STEP", "週次率", [r["step"] for r in rows], [r["weekly_rate"] for r in rows]),
        ("STEP", "伴走回数", [r["step"] for r in rows], [r["n_coach"] for r in rows]),
        ("SP完了日数", "SA gap", [r["sp_days"] for r in rows], [r["sa_gap"] for r in rows]),
    ]:
        r, n = _corr(x, y)
        rs = f"{r:.3f}" if r is not None else "n/a"
        print(f"{a} vs {b}: r={rs} n={n}")


def main() -> int:
    p = argparse.ArgumentParser(description="SP開始30日以上コホート再集計")
    p.add_argument(
        "xlsx",
        type=Path,
        nargs="?",
        default=Path.home() / "Downloads/コミットプラン 2026年6月3日集計.xlsx",
    )
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=4)
    p.add_argument("--snapshot", type=str, default="2026-06-04")
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument(
        "--lstep-tsv",
        type=Path,
        default=Path("data/metadata/lstep_tokushin_userpaste.tsv"),
    )
    p.add_argument(
        "--lstep-xlsx",
        type=Path,
        default=Path.home() / "Downloads/Lステップの顧客データ 2026年6月3日集計.xlsx",
    )
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    lstep_tsv = args.lstep_tsv if args.lstep_tsv.is_absolute() else root / args.lstep_tsv

    snapshot = date.fromisoformat(args.snapshot)
    rows, excluded = load_rows(
        args.xlsx,
        lstep_tsv,
        args.lstep_xlsx,
        args.year,
        args.month,
        snapshot,
        args.min_days,
    )
    print_report(rows, excluded, snapshot, args.min_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
