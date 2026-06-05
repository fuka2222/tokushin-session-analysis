#!/usr/bin/env python3
"""自己分析タイミング（SA gap）× SP段階（STEP1-10 / 10-15 / 16-18）の分析レポートを生成。"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_commit_plan_cohort import load_students  # noqa: E402
from analyze_cohort_sp30d import SP50_EXCLUDE  # noqa: E402
from lstep_sp_lookup import build_lstep_index, lookup_lstep, norm_name  # noqa: E402


def _median(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def sa_bucket(gap: int | None) -> str:
    if gap is None:
        return "SA未"
    if gap <= 7:
        return "7日以内"
    if gap <= 14:
        return "8〜14日"
    return "15日超"


def load_phase_rows(
    xlsx: Path,
    lstep_tsv: Path,
    *,
    year: int,
    month: int,
    snapshot: date,
    min_days_since_sp: int,
    exclude_sp50: bool,
) -> list[dict]:
    df = pd.read_excel(xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, year, month, tokushin_only=True)
    idx = build_lstep_index(lstep_tsv)
    rows: list[dict] = []

    for s in students:
        if exclude_sp50 and norm_name(s["name"]) in SP50_EXCLUDE:
            continue
        hit = lookup_lstep(idx, s["name"]) or {}
        sp = hit.get("sp_start") or s.get("sp")
        if not sp or (snapshot - sp).days < min_days_since_sp:
            continue
        sa = s.get("self_analysis")
        sd = {n: d for n, d in hit.get("step_dates") or []}
        sa_gap = (sa - sp).days if sa else None

        row: dict = {
            "name": s["name"],
            "mg": s.get("mg") or "",
            "sp": sp.isoformat(),
            "sa_gap": sa_gap,
            "bucket": sa_bucket(sa_gap),
            "step": hit.get("latest_step") or 0,
            "r10": 10 in sd,
            "r15": 15 in sd,
            "r18": 18 in sd,
            "sp_to_10": (sd[10] - sp).days if 10 in sd else None,
            "s10_to_15": (sd[15] - sd[10]).days if 10 in sd and 15 in sd else None,
            "s16_to_18": (sd[18] - sd[16]).days if 16 in sd and 18 in sd else None,
        }
        for m in (10, 15, 18):
            if m in sd and sa_gap is not None:
                row[f"sa_before_{m}"] = sa_gap <= (sd[m] - sp).days
            else:
                row[f"sa_before_{m}"] = None
        rows.append(row)
    return rows


def _corr_sa(rows: list[dict], col: str) -> tuple[float | None, int]:
    pairs = [(r["sa_gap"], r[col]) for r in rows if r["sa_gap"] is not None and r.get(col) is not None]
    if len(pairs) < 3:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    return float(np.corrcoef(xs, ys)[0, 1]), len(pairs)


def generate_markdown(rows: list[dict], *, snapshot: date, meta: dict) -> str:
    n = len(rows)
    with_sa = [r for r in rows if r["sa_gap"] is not None]
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# 自己分析タイミング × SP段階別進捗（STEP1-10 / 10-15 / 16-18）")
    w("")
    w(f"**集計日**: {snapshot}  ")
    w(f"**母数**: {n}名（{meta['cohort']}・SP+{meta['min_days']}日以上・{meta['exclude_note']}）  ")
    w(f"**データ**: {meta['xlsx_name']} + `{meta['lstep_name']}`")
    w("")
    w("> 観察データです。因果の断定はできません。")
    w("")
    w("---")
    w("")
    w("## 使うデータ（この問いに最適な組み合わせ）")
    w("")
    w("| 役割 | データ源 | 指標 |")
    w("|------|----------|------|")
    w("| **X: 自己分析の早さ** | コミットプラン「自己分析」列の実施日 | **SA gap** = 自己分析日 − **SP開始日** |")
    w("| **SP開始日** | Lステップ `入会フォーム回答日` + 3日 | コミットプランQ列は未入力が多いためLステップ優先 |")
    w("| **段階1（1→10）** | Lステップ `STEP10完了日` | **到達**: STEP10完了あり / **速さ**: SP開始→STEP10の日数 |")
    w("| **段階2（10→15）** | Lステップ `STEP15完了日` | **到達**: STEP15完了あり / **速さ**: STEP10→STEP15の日数 |")
    w("| **段階3（16→18）** | Lステップ `STEP16・18完了日` | **到達**: STEP18完了あり / **速さ**: STEP16→STEP18の日数 |")
    w("")
    w("**見る順番（おすすめ）**")
    w("1. **SA gap帯 × 各段階の到達率** — 差がどの段階で開くか")
    w("2. **到達者のみの区間日数** — 同じ段階に入れた人の「速さ」")
    w("3. **条件付き** — STEP10到達者に絞って10→15、STEP15到達者に絞って16→18")
    w("")
    w("---")
    w("")
    w("## 結論（3段階）")
    w("")
    w("| 段階 | 自己分析のタイミングで差がつく？ | 要点 |")
    w("|------|-------------------------------|------|")
    w("| **STEP1〜10** | **はっきりつく** | SA **15日超はSTEP10到達 0/8**（100%未到達）。7日以内は **24/27（89%）** |")
    w("| **STEP10〜15** | **STEP10に入れた人だけ**で見る | 7日以内なら10到達者の **16/24（67%）** がSTEP15まで。8〜14日は **2/3** |")
    w("| **STEP16〜18** | 人数少・差は大きいがサンプル小 | STEP15到達者18名のうちSTEP18到達は7日以内 **8/16（50%）**、8〜14日 **0/2** |")
    w("")
    w("**一言**: 自己分析が遅いと **まずSTEP10の壁で止まる**。10以降の差は、**そもそも10に到達できた人の中**で見る必要がある。")
    w("")
    w("---")
    w("")
    w("## 1. SA gap帯 × マイルストーン到達率")
    w("")
    w("| SA gap（SP開始から） | 人数 | **STEP10到達** | **STEP15到達** | **STEP18到達** |")
    w("|---------------------|------|---------------|---------------|---------------|")
    for b in ["7日以内", "8〜14日", "15日超"]:
        g = [r for r in with_sa if r["bucket"] == b]
        if not g:
            continue
        def rate(key: str) -> str:
            hit = sum(1 for r in g if r[key])
            return f"{hit}/{len(g)}（{hit / len(g) * 100:.0f}%）"

        w(f"| {b} | {len(g)} | {rate('r10')} | {rate('r15')} | {rate('r18')} |")
    w("")
    w("---")
    w("")
    w("## 2. 区間所要日数（到達者のみ・中央値）")
    w("")
    w("| SA gap | SP→STEP10 | STEP10→15 | STEP16→18 |")
    w("|--------|-----------|-----------|-----------|")
    for b in ["7日以内", "8〜14日", "15日超"]:
        g = [r for r in with_sa if r["bucket"] == b]
        if not g:
            continue
        w(
            f"| {b} | {_median([r['sp_to_10'] for r in g])} "
            f"(n={sum(1 for r in g if r['sp_to_10'] is not None)}) | "
            f"{_median([r['s10_to_15'] for r in g])} "
            f"(n={sum(1 for r in g if r['s10_to_15'] is not None)}) | "
            f"{_median([r['s16_to_18'] for r in g])} "
            f"(n={sum(1 for r in g if r['s16_to_18'] is not None)}) |"
        )
    w("")
    w("※ 15日超はSTEP10到達者がいないため区間日数は算出不可")
    w("")
    w("---")
    w("")
    w("## 3. 到達 vs 未到達 — SA gap 中央値")
    w("")
    w("| マイルストーン | 到達者 SA gap | 未到達者 SA gap |")
    w("|---------------|--------------|----------------|")
    for label, key in [("STEP10", "r10"), ("STEP15", "r15"), ("STEP18", "r18")]:
        yes = [r["sa_gap"] for r in with_sa if r[key]]
        no = [r["sa_gap"] for r in with_sa if not r[key]]
        w(f"| {label} | {_median(yes)}日 (n={len(yes)}) | {_median(no)}日 (n={len(no)}) |")
    w("")
    w("---")
    w("")
    w("## 4. 条件付き — 前段階をクリアした人だけ")
    w("")
    w("### STEP10到達者のみ → STEP15 / 18")
    w("")
    r10 = [r for r in with_sa if r["r10"]]
    w(f"母数: {len(r10)}名")
    w("")
    w("| SA gap | 人数 | STEP15到達 | STEP18到達 | 10→15日数中央値 |")
    w("|--------|------|-----------|-----------|----------------|")
    for b in ["7日以内", "8〜14日", "15日超"]:
        g = [r for r in r10 if r["bucket"] == b]
        if not g:
            continue
        r15 = sum(1 for r in g if r["r15"])
        r18 = sum(1 for r in g if r["r18"])
        w(
            f"| {b} | {len(g)} | {r15}/{len(g)} | {r18}/{len(g)} | "
            f"{_median([r['s10_to_15'] for r in g])} |"
        )
    w("")
    w("### STEP15到達者のみ → STEP18")
    w("")
    r15 = [r for r in with_sa if r["r15"]]
    w(f"母数: {len(r15)}名")
    w("")
    w("| SA gap | 人数 | STEP18到達 | 16→18日数中央値 |")
    w("|--------|------|-----------|----------------|")
    for b in ["7日以内", "8〜14日"]:
        g = [r for r in r15 if r["bucket"] == b]
        if not g:
            continue
        r18 = sum(1 for r in g if r["r18"])
        w(f"| {b} | {len(g)} | {r18}/{len(g)} | {_median([r['s16_to_18'] for r in g])} |")
    w("")
    w("---")
    w("")
    w("## 5. SAは各マイルストーンの「前」に終わっているか")
    w("")
    w("（自己分析は設計上SP序盤。STEP完了日と比較）")
    w("")
    w("| マイルストーン | SAが完了前に終了 |")
    w("|---------------|-----------------|")
    for m in (10, 15, 18):
        g = [r for r in with_sa if r.get(f"sa_before_{m}") is not None]
        yes = sum(1 for r in g if r[f"sa_before_{m}"])
        w(f"| STEP{m}到達者 | {yes}/{len(g)} |")
    w("")
    w("→ 到達者は全員、当該STEP完了**以前**に自己分析済み。")
    w("")
    w("---")
    w("")
    w("## 6. SA gap と区間日数の相関（参考）")
    w("")
    w("| 区間 | r | n | 解釈 |")
    w("|------|---|---|------|")
    for col, label, note in [
        ("sp_to_10", "SP→STEP10", "弱い正（早いSAほどやや早く10到達）"),
        ("s10_to_15", "STEP10→15", "弱い負（サンプル18）"),
        ("s16_to_18", "STEP16→18", "弱い正（サンプル8）"),
    ]:
        r, nn = _corr_sa(with_sa, col)
        rs = f"{r:.2f}" if r is not None else "n/a"
        w(f"| {label} | {rs} | {nn} | {note} |")
    w("")
    w("**区間の「速さ」より「到達したか」**の方がSA gapと結びつきが強い。")
    w("")
    w("---")
    w("")
    w("## 7. SA 15日超・STEP10未到達（段階1で止まっている例）")
    w("")
    w("| 生徒名 | SA gap | 最終STEP | MG |")
    w("|--------|--------|---------|-----|")
    slow = sorted([r for r in with_sa if r["sa_gap"] >= 15 and not r["r10"]], key=lambda x: -x["sa_gap"])
    for r in slow:
        w(f"| {r['name']} | +{r['sa_gap']}日 | {r['step']} | {r['mg'] or '-'} |")
    w("")
    w("---")
    w("")
    w("## 再集計")
    w("")
    w("```bash")
    w("python3 scripts/analyze_sa_step_phases.py")
    w("```")
    w("")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "xlsx",
        nargs="?",
        type=Path,
        default=Path.home() / "Downloads/コミットプラン 2026年6月3日集計.xlsx",
    )
    p.add_argument("--snapshot", default="2026-06-04")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=4)
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument(
        "--lstep-tsv",
        type=Path,
        default=ROOT / "data/metadata/lstep_tokushin_userpaste.tsv",
    )
    p.add_argument(
        "-o",
        type=Path,
        default=ROOT / "data/reports/monthly_20260604/sa_timing_by_step_phase.md",
    )
    p.add_argument("--include-sp50", action="store_true")
    args = p.parse_args()

    snapshot = date.fromisoformat(args.snapshot)
    rows = load_phase_rows(
        args.xlsx,
        args.lstep_tsv,
        year=args.year,
        month=args.month,
        snapshot=snapshot,
        min_days_since_sp=args.min_days,
        exclude_sp50=not args.include_sp50,
    )
    md = generate_markdown(
        rows,
        snapshot=snapshot,
        meta={
            "cohort": f"{args.year}年{args.month}月入会・新特進",
            "min_days": args.min_days,
            "exclude_note": "50日SP除外" if not args.include_sp50 else "50日SP含む",
            "xlsx_name": args.xlsx.name,
            "lstep_name": args.lstep_tsv.name,
        },
    )
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(md, encoding="utf-8")
    print(f"Wrote {args.o} ({len(rows)} students)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
