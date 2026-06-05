#!/usr/bin/env python3
"""Lステップ: 30日以内初投稿作成完了率（新プログラム STEP1→STEP18）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import pandas as pd

COURSE_ROWS = [
    "全体",
    "講座_ベーシックコース",
    "講座_特進コース",
    "講座_プレミアムプラスコース",
    "講座_プレミアムプラスコース, 講座_コミットコース",
    "講座_特進コース, 講座_ベーシックコース",
]

TARGET_RATE_PCT = 25.0


def parse_date(val) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    dt = pd.to_datetime(val, errors="coerce")
    if pd.isna(dt):
        return None
    d = dt.date()
    return d if 2020 <= d.year <= 2030 else None


def in_cohort_month(d: date | None, year: int, month: int) -> bool:
    return d is not None and d.year == year and d.month == month


def days_between(start: date | None, end: date | None) -> int | None:
    if not start or not end:
        return None
    return (end - start).days


@dataclass
class RateRow:
    course: str
    denominator: int
    completed: int
    completion_rate_pct: float
    within_30: int
    within_30_rate_pct: float


def _filter_course(df: pd.DataFrame, course_key: str) -> pd.DataFrame:
    if course_key == "全体":
        return df
    return df[df["コース"].astype(str).str.strip() == course_key]


def _aggregate(
    df: pd.DataFrame,
    *,
    start_col: str,
    complete_col: str,
    year: int,
    month: int,
) -> list[RateRow]:
    rows: list[RateRow] = []
    for ck in COURSE_ROWS:
        sub = _filter_course(df, ck)
        denom = completed = within30 = 0
        for _, r in sub.iterrows():
            start = parse_date(r.get(start_col))
            if not in_cohort_month(start, year, month):
                continue
            denom += 1
            done = parse_date(r.get(complete_col))
            if done:
                completed += 1
                gap = days_between(start, done)
                if gap is not None and gap <= 30:
                    within30 += 1
        rows.append(
            RateRow(
                course=ck,
                denominator=denom,
                completed=completed,
                completion_rate_pct=round(completed / denom * 100, 1) if denom else 0.0,
                within_30=within30,
                within_30_rate_pct=round(within30 / denom * 100, 1) if denom else 0.0,
            )
        )
    return rows


def load_program_old(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="投稿プログラム（旧）")
    df = df[df["表示名"].notna() & (df["表示名"].astype(str).str.strip() != "")]
    return df


def load_program_new(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="投稿プログラム（新）")
    df = df[df["表示名"].notna() & (df["表示名"].astype(str).str.strip() != "")]
    return df


def compute_first_post_30d(
    lstep_path: Path,
    *,
    year: int = 2026,
    month: int = 4,
    new_program_only: bool = True,
) -> dict:
    new_df = load_program_new(lstep_path)
    new_rows = _aggregate(
        new_df,
        start_col="STEP1完了日",
        complete_col="STEP18完了日",
        year=year,
        month=month,
    )
    new_all = new_rows[0]
    result_pct = new_all.within_30_rate_pct
    gap = round(TARGET_RATE_PCT - result_pct, 1)

    out: dict = {
        "year": year,
        "month": month,
        "program_scope": "新プログラムのみ",
        "target_rate_pct": TARGET_RATE_PCT,
        "overall_within_30_rate_pct": result_pct,
        "target_gap_pct": gap,
        "new_program": new_rows,
        "notes": {
            "denominator": "STEP1完了日が指定月",
            "numerator": "STEP18完了日あり",
            "within_30": "STEP1→STEP18が30日以内",
        },
    }
    if not new_program_only:
        old_df = load_program_old(lstep_path)
        out["old_program"] = _aggregate(
            old_df,
            start_col="【SP】受講開始日",
            complete_col="【PP】Step9完了日",
            year=year,
            month=month,
        )
    return out


def rate_rows_to_df(rows: list[RateRow], program: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "プログラム": program,
                "コース": r.course,
                "分母": r.denominator,
                "完了人数": r.completed,
                "完了率%": r.completion_rate_pct,
                "30日以内達成": r.within_30,
                "30日以内達成率%": r.within_30_rate_pct,
            }
            for r in rows
        ]
    )


def format_markdown(result: dict) -> str:
    y, m = result["year"], result["month"]
    new_all = result["new_program"][0]
    lines = [
        f"# 30日以内初投稿作成完了率（{y}年{m}月コホート）",
        "",
        f"- **集計対象**: {result.get('program_scope', '新プログラムのみ')}",
        f"- **目標（30日以内達成率）**: **{result['target_rate_pct']}%**",
        f"- **結果**: **{result['overall_within_30_rate_pct']}%**"
        f"（{new_all.within_30}名 / 分母{new_all.denominator}名）",
        f"- **目標との差**: {result.get('target_gap_pct', 0):+.1f}ポイント",
        "",
        "## 【新プログラム】",
        "",
        "分母: STEP1完了日が対象月 / 分子: STEP18完了 / 30日以内: STEP1→STEP18≤30日",
        "",
        "| コース | 分母 | 完了人数 | 完了率 | 30日以内達成 | 30日以内達成率 |",
        "|--------|------|----------|--------|--------------|----------------|",
    ]
    for r in result["new_program"]:
        lines.append(
            f"| {r.course} | {r.denominator} | {r.completed} | {r.completion_rate_pct}% | "
            f"{r.within_30} | {r.within_30_rate_pct}% |"
        )
    return "\n".join(lines) + "\n"
