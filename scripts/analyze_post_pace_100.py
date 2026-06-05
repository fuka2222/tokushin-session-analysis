#!/usr/bin/env python3
"""コミット生徒の月次投稿ペース vs 100投稿（半年）目標の分析"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HEADER_ROW = 10
DATA_START = 11
MONTH_COLS = range(15, 22)  # P〜V: 0〜6ヶ月目（単月投稿数）
COMMIT_EXCLUDE = {"こしのあきこ", "いわかわのぶゆき", "いわかわ　のぶゆき"}

# 半年100投稿: 単月(累計) = 0(0), 17(17), 18(35), 21(56), 22(78), 22(100)
BENCH_MONTHLY = [0, 17, 18, 21, 22, 22]
BENCH_CUM = [0, 17, 35, 56, 78, 100]

# 80投稿目安: 0(0), 13(13), 14(27), 17(44), 18(62), 18(80)
BENCH_80_MONTHLY = [0, 13, 14, 17, 18, 18]
BENCH_80_CUM = [0, 13, 27, 44, 62, 80]

# 60投稿目安: 0(0), 10(10), 11(21), 13(34), 13(47), 13(60)
BENCH_60_MONTHLY = [0, 10, 11, 13, 13, 13]
BENCH_60_CUM = [0, 10, 21, 34, 47, 60]

# 旧120目標（新 月次投稿数 シート row7-8）
OLD120_CUM = [0, 0, 20, 41, 66, 93, 120]


def norm_name(s: str) -> str:
    return str(s).replace(" ", "").replace("　", "").strip()


def parse_val(v) -> float:
    if pd.isna(v) or str(v).strip() in ("", "ー", "-", "nan"):
        return np.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def load_monthly_students(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="新 月次投稿数", header=None)
    rows = []
    for i in range(DATA_START, len(raw)):
        row = raw.iloc[i]
        name = row[4]
        if pd.isna(name) or str(name).strip() in ("", "生徒名"):
            continue
        monthly = [parse_val(row[c]) for c in MONTH_COLS]
        cum: list[float] = []
        total = 0.0
        for v in monthly:
            if np.isnan(v):
                cum.append(np.nan)
            else:
                total += v
                cum.append(total)
        rows.append(
            {
                "name": str(name).strip(),
                "name_norm": norm_name(name),
                "status": row[2],
                "mg": str(row[6]).strip() if pd.notna(row[6]) else "",
                "grad_posts_sheet": parse_val(row[13]),
                "current_posts": parse_val(row[12]),
                "monthly": monthly,
                "cumulative": cum,
            }
        )
    return pd.DataFrame(rows)


def load_latest_grad_posts(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="コミット月次投稿数", header=4)
    df = df.rename(columns={"Unnamed: 1": "mg_posts"})
    df["name_norm"] = df["生徒名"].apply(norm_name)
    return df[["name_norm", "生徒名", "mg_posts", "卒業時投稿数"]].rename(
        columns={"生徒名": "name", "卒業時投稿数": "grad_posts_latest"}
    )


def load_nov_graduates(path: Path) -> pd.DataFrame:
    """11月入会卒業者リスト。中途解約行・既知の解約者名を除外。"""
    df = pd.read_excel(path, sheet_name="コミット11月入会卒業者リスト", header=0)
    for col in df.columns:
        if df[col].astype(str).str.contains("中途解約", na=False).any():
            df = df[~df[col].astype(str).str.contains("中途解約", na=False)].copy()
    exclude = {norm_name(n) for n in COMMIT_EXCLUDE}
    df = df[~df["生徒名"].apply(norm_name).isin(exclude)].copy()
    df["name_norm"] = df["生徒名"].apply(norm_name)
    return df.sort_values("卒業時投稿数", ascending=False)


def month_stats(sub: pd.DataFrame, month: int, target: float) -> dict:
    vals = []
    for cum in sub["cumulative"]:
        if month < len(cum) and not np.isnan(cum[month]):
            vals.append(cum[month])
    if not vals:
        return {"n": 0}
    arr = np.array(vals)
    on = int((arr >= target).sum())
    return {
        "n": len(vals),
        "target": target,
        "on_track": on,
        "on_track_pct": round(on / len(vals) * 100, 1),
        "median": round(float(np.median(arr)), 1),
        "mean": round(float(arr.mean()), 1),
        "p25": round(float(np.percentile(arr, 25)), 1),
        "p75": round(float(np.percentile(arr, 75)), 1),
    }


def latest_month_idx(cum: list[float]) -> int:
    last = -1
    for i, v in enumerate(cum):
        if not np.isnan(v):
            last = i
    return last


def pace_label(actual: float, target: float) -> str:
    if np.isnan(actual):
        return "データなし"
    ratio = actual / target if target > 0 else (1.0 if actual >= 0 else 0.0)
    if ratio >= 1.0:
        return "達成"
    if ratio >= 0.8:
        return "やや遅れ"
    if ratio >= 0.5:
        return "遅れ"
    return "大幅遅れ"


def build_report(
    students: pd.DataFrame,
    posts: pd.DataFrame,
    nov: pd.DataFrame,
    commit_plan: Path,
    posts_file: Path,
) -> str:
    merged = students.merge(
        posts[["name_norm", "grad_posts_latest"]], on="name_norm", how="left"
    )
    grads = merged[merged["status"] == "卒業"].copy()
    active = merged[merged["status"] == "在学中"].copy()

    lines = [
        "# コミット投稿ペース分析 — 100投稿（半年）目標",
        "",
        f"**集計日**: {pd.Timestamp.now().strftime('%Y-%m-%d')}",
        f"**月次データ**: `{commit_plan.name}` → シート `新 月次投稿数`（P列〜: 0〜6ヶ月目・単月投稿数）",
        f"**卒業時投稿数**: `{posts_file.name}` → シート `コミット月次投稿数`",
        "",
        "## 100投稿目標（半年）",
        "",
        "| 月 | 単月目標 | 累計目標 |",
        "|----|---------|---------|",
    ]
    for m in range(6):
        lines.append(f"| {m}ヶ月目 | {BENCH_MONTHLY[m]} | {BENCH_CUM[m]} |")
    lines.append("")

    # Graduation totals
    lines += [
        "## 1. 卒業時合計投稿数（最新データ）",
        "",
        f"- コミットプラン全卒業者: **{len(grads)}名**",
        f"- 平均 **{grads['grad_posts_latest'].mean():.1f}本** / 中央値 **{grads['grad_posts_latest'].median():.1f}本**",
        f"- 100投稿以上: **{(grads['grad_posts_latest'] >= 100).sum()}名** ({(grads['grad_posts_latest'] >= 100).mean() * 100:.1f}%)",
        f"- 60投稿以上: **{(grads['grad_posts_latest'] >= 60).sum()}名** ({(grads['grad_posts_latest'] >= 60).mean() * 100:.1f}%)",
        "",
    ]

    # Historical pace vs benchmark
    lines += [
        "## 2. 過去卒業生 vs 100投稿ペース（各月末累計）",
        "",
        "過去130名の卒業生が、在学期間中に各月時点で新目標を満たしていた割合。",
        "",
        "| 月 | 目標累計 | データあり | 目標達成 | 達成率 | 中央値 | 平均 | P25 | P75 |",
        "|----|---------|-----------|---------|-------|-------|------|-----|-----|",
    ]
    for m in range(6):
        st = month_stats(grads, m, BENCH_CUM[m])
        if st["n"] == 0:
            continue
        lines.append(
            f"| {m}ヶ月目 | {st['target']} | {st['n']} | {st['on_track']} | {st['on_track_pct']}% | "
            f"{st['median']} | {st['mean']} | {st['p25']} | {st['p75']} |"
        )

    lines += [
        "",
        "### 解釈",
        "",
        "- 新100投稿ペースは、**過去卒業生の中央値を大きく上回る**設定",
        f"- 5ヶ月目時点: 目標100本に対し、過去卒業生の中央値は **{month_stats(grads, 5, 100)['median']}本**",
        f"- それでも最終的に100本以上達成した卒業生は **{(grads['grad_posts_latest'] >= 100).sum()}名** — 後半に加速したケースあり",
        "",
        "## 3. 11月入会卒業者（23名）の月次ペース",
        "",
        "除外: 中途解約2名（こしのあきこ、いわかわのぶゆき）",
        "",
        f"- 平均卒業時投稿数: **{nov['卒業時投稿数'].mean():.1f}本** / 中央値 **{nov['卒業時投稿数'].median():.1f}本**",
        f"- 100投稿以上: **{(nov['卒業時投稿数'] >= 100).sum()}名** / 60投稿以上: **{(nov['卒業時投稿数'] >= 60).sum()}名**",
        "",
        "| 生徒名 | MG | 卒業時 | M1累計 | M2 | M3 | M4 | M5 | 5ヶ月時判定 |",
        "|--------|-----|-------|-------|-----|-----|-----|-----|------------|",
    ]

    nov_merged = nov.merge(students, on="name_norm", how="left")
    nov_merged = nov_merged.sort_values("卒業時投稿数", ascending=False)
    for _, r in nov_merged.iterrows():
        cum = r.get("cumulative") or [np.nan] * 7
        m_vals = []
        for m in range(1, 6):
            v = cum[m] if m < len(cum) else np.nan
            m_vals.append("—" if np.isnan(v) else str(int(v)))
        m5 = cum[5] if len(cum) > 5 else np.nan
        label = pace_label(m5, BENCH_CUM[5]) if not np.isnan(m5) else "—"
        mg = r.get("mg") or r.get("担当MG") or ""
        lines.append(
            f"| {r['生徒名']} | {mg} | {int(r['卒業時投稿数'])} | "
            f"{m_vals[0]} | {m_vals[1]} | {m_vals[2]} | {m_vals[3]} | {m_vals[4]} | {label} |"
        )

    # Active students
    active["month_idx"] = active["cumulative"].apply(latest_month_idx)
    active["latest_cum"] = active.apply(
        lambda r: r["cumulative"][r["month_idx"]] if r["month_idx"] >= 0 else np.nan, axis=1
    )

    lines += [
        "",
        "## 4. 在学中（334名）の現時点ペース",
        "",
        "各生徒の最新入力月時点での累計投稿数と、100投稿ペースとの比較。",
        "",
        "| 最新月 | 人数 | 目標累計 | 目標達成 | 達成率 | 中央値 | 平均 |",
        "|--------|------|---------|---------|-------|-------|------|",
    ]
    for m in range(7):
        sub = active[active["month_idx"] == m]
        if len(sub) == 0:
            continue
        tgt = BENCH_CUM[m] if m < len(BENCH_CUM) else 100
        st = month_stats(sub, m, tgt)
        lines.append(
            f"| {m}ヶ月目 | {len(sub)} | {tgt} | {st.get('on_track', 0)} | "
            f"{st.get('on_track_pct', 0)}% | {st.get('median', '—')} | {st.get('mean', '—')} |"
        )

    def is_far_behind(r) -> bool:
        m = int(r["month_idx"])
        if m < 0 or m >= len(BENCH_CUM):
            return False
        if np.isnan(r["latest_cum"]):
            return False
        return r["latest_cum"] < BENCH_CUM[m] * 0.5

    behind = active[(active["month_idx"] >= 0) & active.apply(is_far_behind, axis=1)].sort_values(
        "latest_cum"
    )

    lines += [
        "",
        f"### 要注意（最新月時点で目標の50%未満）: {len(behind)}名",
        "",
    ]
    if len(behind) > 0:
        lines.append("| 生徒名 | MG | 最新月 | 累計 | 目標 | 比率 |")
        lines.append("|--------|-----|--------|------|------|------|")
        for _, r in behind.head(20).iterrows():
            m = r["month_idx"]
            tgt = BENCH_CUM[m]
            ratio = r["latest_cum"] / tgt * 100 if tgt > 0 else 0
            lines.append(
                f"| {r['name']} | {r['mg']} | {m}ヶ月目 | {int(r['latest_cum'])} | {tgt} | {ratio:.0f}% |"
            )
        if len(behind) > 20:
            lines.append(f"| …他 {len(behind) - 20}名 | | | | | |")

    lines += [
        "",
        "## 5. 旧120目標との比較",
        "",
        "| 月 | 旧120累計 | 新100累計 | 過去卒業生中央値 |",
        "|----|----------|----------|----------------|",
    ]
    for m in range(6):
        old = OLD120_CUM[m + 1] if m + 1 < len(OLD120_CUM) else OLD120_CUM[-1]
        med = month_stats(grads, m, BENCH_CUM[m]).get("median", "—")
        lines.append(f"| {m}ヶ月目 | {old} | {BENCH_CUM[m]} | {med} |")

    lines += [
        "",
        "---",
        f"*再集計: `python scripts/analyze_post_pace_100.py --commit-plan \"{commit_plan}\" --posts \"{posts_file}\"`*",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit-plan",
        type=Path,
        default=Path.home() / "Downloads" / "コミットプラン (8).xlsx",
    )
    parser.add_argument(
        "--posts",
        type=Path,
        default=Path.home() / "Downloads" / "投稿数集計用2026年6月3日DL.xlsx",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "reports",
    )
    args = parser.parse_args()

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    students = load_monthly_students(args.commit_plan)
    posts = load_latest_grad_posts(args.posts)
    nov = load_nov_graduates(args.posts)

    merged = students.merge(
        posts[["name_norm", "grad_posts_latest"]], on="name_norm", how="left"
    )
    merged.to_csv(out / "commit_monthly_pace.csv", index=False, encoding="utf-8-sig")

    report = build_report(students, posts, nov, args.commit_plan, args.posts)
    report_path = out / "post_pace_100_benchmark.md"
    report_path.write_text(report, encoding="utf-8")

    grads = merged[merged["status"] == "卒業"]
    print("=== 卒業時投稿数（最新） ===")
    print(f"  人数: {len(grads)}")
    print(f"  平均: {grads['grad_posts_latest'].mean():.1f}")
    print(f"  100以上: {(grads['grad_posts_latest'] >= 100).sum()}")
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
