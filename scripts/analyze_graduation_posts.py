#!/usr/bin/env python3
"""コミット・プレミアムプラス 卒業時投稿数分析（投稿数集計用.xlsx）"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

COMMIT_SHEET = "コミット11月入会卒業者リスト"
PP_SHEET = "#03シート 11月入会者"
COMMIT_TARGET = 60
COMMIT_EXCLUDE = ["こしのあきこ", "いわかわのぶゆき", "いわかわ　のぶゆき"]
PP_CUTOFF = datetime(2026, 5, 28)
PP_HEADER_ROW = 2
PP_DATA_START = 3
PP_COL_NAME = 1
PP_COL_MG = 2
PP_COL_POSTS = 5
PP_COL_AA = 26
PP_SESSION_COLS = [6, 10, 14, 18, 22, 26]


def norm_name(s: str) -> str:
    return str(s).replace(" ", "").replace("　", "").strip()


def analyze_commit(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_excel(path, sheet_name=COMMIT_SHEET, header=0)
    exclude = {norm_name(n) for n in COMMIT_EXCLUDE}
    df = df[~df["生徒名"].apply(norm_name).isin(exclude)].copy()
    df["達成率%"] = (df["卒業時投稿数"] / COMMIT_TARGET * 100).round(1)

    summary = {
        "人数": len(df),
        "平均投稿数": round(df["卒業時投稿数"].mean(), 1),
        "中央値": round(df["卒業時投稿数"].median(), 1),
        "目標60投稿": COMMIT_TARGET,
        "目標達成率%": round(df["卒業時投稿数"].mean() / COMMIT_TARGET * 100, 1),
        "60投稿以上": int((df["卒業時投稿数"] >= COMMIT_TARGET).sum()),
        "60投稿以上率%": round((df["卒業時投稿数"] >= COMMIT_TARGET).mean() * 100, 1),
    }
    return df, summary


def row_has_duplicate_marker(row: pd.Series) -> bool:
    for val in row:
        if pd.notna(val) and "重複" in str(val):
            return True
    return False


def analyze_premium_plus(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_excel(path, sheet_name=PP_SHEET, header=None)
    rows = []
    for i in range(PP_DATA_START, len(raw)):
        name = raw.iloc[i, PP_COL_NAME]
        if pd.isna(name) or not str(name).strip():
            continue
        if row_has_duplicate_marker(raw.iloc[i]):
            continue
        aa_val = raw.iloc[i, PP_COL_AA]
        if pd.isna(aa_val):
            continue
        aa_date = pd.to_datetime(aa_val)
        if aa_date > PP_CUTOFF:
            continue
        posts = float(raw.iloc[i, PP_COL_POSTS]) if pd.notna(raw.iloc[i, PP_COL_POSTS]) else 0.0
        mg = str(raw.iloc[i, PP_COL_MG]) if pd.notna(raw.iloc[i, PP_COL_MG]) else "不明"
        rows.append(
            {
                "生徒名": str(name).strip(),
                "担当MG": mg,
                "合計投稿数": posts,
                "6回目実施日": aa_date.strftime("%Y-%m-%d"),
            }
        )
    df = pd.DataFrame(rows)
    summary = {
        "人数": len(df),
        "平均投稿数": round(df["合計投稿数"].mean(), 1) if len(df) else 0,
        "中央値": round(df["合計投稿数"].median(), 1) if len(df) else 0,
        "集計条件": "重複行除外・AA列(6回目)あり・6回目実施日≦2026-05-28",
    }
    return df, summary


def mg_summary_commit(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("担当MG").agg(
        人数=("卒業時投稿数", "count"),
        平均投稿数=("卒業時投稿数", "mean"),
        目標達成率=("達成率%", "mean"),
    )
    g["60達成人数"] = df.groupby("担当MG")["卒業時投稿数"].apply(lambda x: (x >= COMMIT_TARGET).sum())
    g["60達成率"] = (g["60達成人数"] / g["人数"] * 100).round(1)
    return g.round(1).sort_values("平均投稿数", ascending=False).reset_index()


def mg_summary_pp(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby("担当MG")
        .agg(人数=("合計投稿数", "count"), 平均投稿数=("合計投稿数", "mean"))
        .round(1)
        .sort_values("平均投稿数", ascending=False)
        .reset_index()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path.home() / "Downloads" / "投稿数集計用.xlsx",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "reports",
    )
    args = parser.parse_args()

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    commit_df, commit_sum = analyze_commit(args.input)
    pp_df, pp_sum = analyze_premium_plus(args.input)

    commit_df.to_csv(out / "commit_graduates_posts.csv", index=False, encoding="utf-8-sig")
    mg_summary_commit(commit_df).to_csv(out / "commit_by_mg.csv", index=False, encoding="utf-8-sig")
    pp_df.to_csv(out / "premium_plus_posts.csv", index=False, encoding="utf-8-sig")
    mg_summary_pp(pp_df).to_csv(out / "premium_plus_by_mg.csv", index=False, encoding="utf-8-sig")

    print("=== コミットコース（11月入会卒業者）===")
    for k, v in commit_sum.items():
        print(f"  {k}: {v}")
    print("\n--- MG別 ---")
    print(mg_summary_commit(commit_df).to_string(index=False))

    print("\n=== プレミアムプラス（11月入会・6回目まで完了）===")
    for k, v in pp_sum.items():
        print(f"  {k}: {v}")
    print("\n--- MG別（人数3人以上）---")
    mg_pp = mg_summary_pp(pp_df)
    print(mg_pp[mg_pp["人数"] >= 3].to_string(index=False))


if __name__ == "__main__":
    main()
