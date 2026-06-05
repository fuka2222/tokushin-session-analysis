#!/usr/bin/env python3
"""セッション × SP相関レポート（Markdown）を生成する。"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_cohort_sp30d import _corr, _median, load_rows  # noqa: E402


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.1f}%" if total else "-"


def fmt_sa_gap(days: int | None) -> str:
    if days is None:
        return "-"
    return f"{days:+d}日"


def mean(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return statistics.mean(v) if v else None


def band_table(rows: list[dict], total: int) -> list[str]:
    lines = [
        "| SA gap | 人数 | 全体中% | STEP中央値 | STEP平均 |",
        "|--------|------|---------|-----------|-----------|",
    ]
    for label, pred in [
        ("**7日以内**", lambda g: g <= 7),
        ("8〜14日", lambda g: 8 <= g <= 14),
        ("**15日超**", lambda g: g >= 15),
    ]:
        g = [r for r in rows if r["sa_gap"] is not None and pred(r["sa_gap"])]
        steps = [r["step"] for r in g]
        m = mean(steps)
        m_s = f"{m:.1f}" if m is not None else "-"
        lines.append(
            f"| {label} | {len(g)}名 | {pct(len(g), total)} | "
            f"**{_median(steps)}** | {m_s} |"
        )
    return lines


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "xlsx",
        nargs="?",
        type=Path,
        default=Path.home() / "Downloads/コミットプラン 2026年6月3日集計.xlsx",
    )
    p.add_argument("--snapshot", default="2026-06-04")
    p.add_argument(
        "--lstep-tsv",
        type=Path,
        default=ROOT / "data/metadata/lstep_tokushin_userpaste.tsv",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=ROOT / "data/reports/monthly_20260604",
    )
    args = p.parse_args()
    snapshot = date.fromisoformat(args.snapshot)
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows, _ = load_rows(args.xlsx, args.lstep_tsv, None, 2026, 4, snapshot, 0)
    rows30, excluded30 = load_rows(
        args.xlsx, args.lstep_tsv, None, 2026, 4, snapshot, 30
    )
    n = len(all_rows)
    n30 = len(rows30)

    slow15 = sorted(
        [r for r in all_rows if r["sa_gap"] is not None and r["sa_gap"] >= 15],
        key=lambda x: -x["sa_gap"],
    )
    weekly_low = sorted(
        [
            r
            for r in all_rows
            if r["weekly_rate"] is not None and r["weekly_rate"] < 0.5
        ],
        key=lambda x: x["step"],
        reverse=True,
    )
    sp_incomplete = sorted(
        [r for r in all_rows if r["sp_days"] is None],
        key=lambda x: x["name"],
    )

    # SA x coach cross
    def cross_pat(r: dict) -> str:
        sa_early = r["sa_gap"] is not None and r["sa_gap"] <= 7
        coach_early = r["coach_sp"] is not None and r["coach_sp"] <= 14
        if sa_early and coach_early:
            return "SA早×伴走早"
        if sa_early and not coach_early:
            return "SA早×伴走遅"
        if not sa_early and coach_early:
            return "SA遅×伴走早"
        return "SA遅×伴走遅"

    cross_counts: dict[str, list] = {}
    for r in all_rows:
        cross_counts.setdefault(cross_pat(r), []).append(r)

    # SA -> coach gap (coach >= sa)
    sa_coach_gaps = []
    for r in all_rows:
        if r["sa_coach"] is not None:
            sa_coach_gaps.append((r["sa_coach"], r))

    # correlations
    corr_pairs = [
        ("STEP", "SA gap", [r["step"] for r in all_rows], [r["sa_gap"] for r in all_rows]),
        ("STEP", "週次率", [r["step"] for r in all_rows], [r["weekly_rate"] for r in all_rows]),
        ("STEP", "伴走回数", [r["step"] for r in all_rows], [r["n_coach"] for r in all_rows]),
        ("STEP", "初回伴走(SPから)", [r["step"] for r in all_rows], [r["coach_sp"] for r in all_rows]),
        ("STEP", "SA→伴走間隔", [r["step"] for r in all_rows], [r["sa_coach"] for r in all_rows]),
        ("SP完了日数", "SA gap", [r["sp_days"] for r in all_rows], [r["sa_gap"] for r in all_rows]),
        ("SP完了日数", "伴走回数", [r["sp_days"] for r in all_rows], [r["n_coach"] for r in all_rows]),
        ("SP完了日数", "週次率", [r["sp_days"] for r in all_rows], [r["weekly_rate"] for r in all_rows]),
    ]

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# セッション実施状況 × SPプログラム進行 相関分析（採用版）")
    w("")
    w(f"**集計日**: {snapshot}  ")
    w(f"**対象**: 2026年4月入会・新特進コホート **{n}名**（Lステップ結合済）  ")
    w(
        f"**SP開始+30日以上のみの再集計（{n30}名）**: "
        f"[`session_vs_sp_correlation_202604_sp30d.md`](session_vs_sp_correlation_202604_sp30d.md)"
    )
    w("")
    w("**データソース**:")
    w(f"- コミットプラン `{args.xlsx.name}` — セッション実施状況管理（自己分析・伴走0回目〜）")
    w("- Lステップ `lstep_tokushin_userpaste.tsv` — SP開始（入会フォーム+3日）/ STEP1〜19完了日")
    w("")
    w("> 観察データに基づく相関分析です。**因果関係の断定はできません。**")
    w("")
    w("---")
    w("")
    w("## 結論サマリー")
    w("")
    w("| 観点 | 見えていること |")
    w("|------|---------------|")
    sa7 = [r for r in all_rows if r["sa_gap"] is not None and r["sa_gap"] <= 7]
    sa15 = [r for r in all_rows if r["sa_gap"] is not None and r["sa_gap"] >= 15]
    w(
        f"| **自己分析の早さ → STEP** | **最もはっきり**。SA gap 7日以内はSTEP中央値"
        f"{_median([r['step'] for r in sa7])}。15日超{len(sa15)}名はSTEP中央値0（SP未完了{sum(1 for r in sa15 if r['sp_days'] is None)}名） |"
    )
    gaps_sc = [g for g, _ in sa_coach_gaps]
    w(
        f"| **SA → 初回伴走の間隔** | 中央値**{_median(gaps_sc):.0f}日**（n={len(gaps_sc)}）。設計上「自己分析→伴走」が主流 |"
    )
    r_nc, _ = _corr([r["step"] for r in all_rows], [r["n_coach"] for r in all_rows])
    w(
        f"| **伴走の回数** | STEPと連動（r={r_nc:.2f}）するが、**SPを早く終わらせる効果は弱い** |"
    )
    r_wr, _ = _corr([r["step"] for r in all_rows], [r["weekly_rate"] for r in all_rows])
    w(
        f"| **週次ペース** | STEPと r={r_wr:.2f} だが、**単独の警戒指標には不向き**（週次50%未満でもSTEP進行の例外あり） |"
    )
    w(
        "| **伴走の役割** | SPの「加速器」より、**並行・継続サポート**。効くのは**いつ始めたか** |"
    )
    w("")
    w("**運用で最優先**: SP開始〜**1週間以内の自己分析** → できれば**自己分析後1〜2週間以内に伴走**。")
    w("")
    w("**5/30版（38名）からの主な変化**: 母数44名・SP60日以内完了が増加（30/44）。SA15日超は11名・うちSP未完了10名で構造は同じ。")
    w("")
    w("---")
    w("")
    w("## 定義")
    w("")
    w("| 用語 | 定義 |")
    w("|------|------|")
    w("| **SP開始日** | Lステップ「入会フォーム回答日」+ 3日 |")
    w("| **SA gap** | 自己分析セッション実施日 − SP開始日（日数）。小さい＝早い |")
    w("| **自己分析（SA）** | コミットプラン 自己分析列 |")
    w("| **コーチング（伴走）** | コミットプラン 伴走0回目〜。セルに日付がある回数 |")
    w("| **SP完了日数** | SP開始から STEP19完了までの日数 |")
    w("| **STEP進捗** | Lステップ STEP1〜19 の最終完了STEP（0＝未着手） |")
    w("| **週次率** | 隣接伴走間隔が5〜9日だった割合（2回未満は判定不可） |")
    w("| **50日SP** | 50日版SP。**STEP比較から除外**する5名（下記） |")
    w("")
    w("**50日SP除外**: あさのえりか / あらきりえこ / あわやしょうま / ふっくみな / しまおかみさと")
    w("")
    w("---")
    w("")
    w("## 1. 自己分析のタイミング × SP進捗")
    w("")
    w("### SA gap（SP開始から自己分析まで）")
    w("")
    lines.extend(band_table(all_rows, n))
    w("")
    w(f"- **15日超{len(sa15)}名**: STEP中央値0。SP未完了 **{sum(1 for r in sa15 if r['sp_days'] is None)}名**。")
    w("")
    w("### SP完了速度 × 自己分析")
    w("")
    w("#### 累積：SP開始から○日以内にSP完了")
    w("")
    w("| SP完了まで | 完了人数 | 全体中% | SA gap中央値 | SA 7日以内 | STEP中央値 |")
    w("|-----------|---------|---------|-------------|-----------|-----------|")
    for t in [15, 20, 25, 30, 35, 40, 45, 60]:
        grp = [r for r in all_rows if r["sp_days"] is not None and r["sp_days"] <= t]
        gaps = [r["sa_gap"] for r in grp if r["sa_gap"] is not None]
        sa7c = sum(1 for r in grp if r["sa_gap"] is not None and r["sa_gap"] <= 7)
        w(
            f"| {t}日以内 | {len(grp)}名 | {pct(len(grp), n)} | {_median(gaps)} | "
            f"{sa7c}/{len(grp) or 1} | {_median([r['step'] for r in grp])} |"
        )
    w("")
    w(f"**SP未完了（{len(sp_incomplete)}名）**: " + "・".join(r["name"] for r in sp_incomplete))
    w("")
    w("#### SA gap帯 × SP完了")
    w("")
    w("| SA gap | 人数 | SP30日以内で完了 | SP未完了 |")
    w("|--------|------|-----------------|----------|")
    for label, pred in [
        ("7日以内", lambda g: g <= 7),
        ("8〜14日", lambda g: 8 <= g <= 14),
        ("15日超", lambda g: g >= 15),
    ]:
        g = [r for r in all_rows if r["sa_gap"] is not None and pred(r["sa_gap"])]
        sp30 = sum(
            1
            for r in g
            if r["sp_days"] is not None and r["sp_days"] <= 30
        )
        nd = sum(1 for r in g if r["sp_days"] is None)
        w(f"| {label} | {len(g)}名 | {sp30}/{len(g)} | {nd}名 |")
    w("")
    w("### STEP0・SP未完了 — SA gap 15日超（要フォロー）")
    w("")
    w("| 生徒名 | SA gap | 伴走 | MG | 備考 |")
    w("|--------|--------|------|-----|------|")
    for r in slow15:
        note = "50日SP" if r.get("sp50") else "30日SP"
        w(f"| {r['name']} | {fmt_sa_gap(r['sa_gap'])} | {r['n_coach']}回 | {r['mg'] or '-'} | {note} |")
    w("")
    w("---")
    w("")
    w("## 2. コーチング週次ペース × STEP進捗")
    w("")
    w("| 週次ペース | 人数 | STEP中央値 | 全体中% |")
    w("|-----------|------|-----------|---------|")
    for label, pred in [
        ("全間隔が週次（5-9日）", lambda r: r["all_weekly"] is True),
        ("週次率 50〜99%", lambda r: r["weekly_rate"] is not None and 0.5 <= r["weekly_rate"] < 1),
        ("**週次率 50%未満**", lambda r: r["weekly_rate"] is not None and r["weekly_rate"] < 0.5),
        ("週次判定不可", lambda r: r["weekly_rate"] is None),
    ]:
        g = [r for r in all_rows if pred(r)]
        w(f"| {label} | {len(g)}名 | {_median([r['step'] for r in g])} | {pct(len(g), n)} |")
    w("")
    r_wr2, _ = _corr([r["step"] for r in all_rows], [r["weekly_rate"] for r in all_rows])
    w(f"STEP vs 週次率 **r = {r_wr2:.2f}**（§4）。")
    w("")
    w("### 週次率 50%未満")
    w("")
    w("| 生徒名 | STEP | SA gap | 週次率 | 伴走 | MG | 備考 |")
    w("|--------|------|--------|--------|------|-----|------|")
    for r in weekly_low:
        wr = r["weekly_rate"]
        wr_s = f"{wr * 100:.0f}%" if wr is not None else "-"
        sa = fmt_sa_gap(r["sa_gap"])
        note = ""
        if r["step"] >= 10:
            note = "週次悪いがSTEP進行"
        if r.get("sp50"):
            note = (note + " " if note else "") + "50日SP"
        w(
            f"| {r['name']} | {r['step']} | {sa} | {wr_s} | {r['n_coach']}回 | "
            f"{r['mg'] or '-'} | {note} |"
        )
    w("")
    w("**推奨の警戒条件**: `SA gap 14日超 & STEP5未満`")
    w("")
    w("---")
    w("")
    w("## 3. 自己分析・伴走の「早さ」とSTEP")
    w("")
    w("### 自己分析の早さ × 初回伴走の早さ")
    w("")
    w("| パターン | 人数 | 全体中% | STEP中央値 | STEP0 |")
    w("|---------|------|---------|-----------|-------|")
    for pat in ["SA早×伴走早", "SA早×伴走遅", "SA遅×伴走早", "SA遅×伴走遅"]:
        g = cross_counts.get(pat, [])
        w(
            f"| {pat} | {len(g)}名 | {pct(len(g), n)} | "
            f"{_median([r['step'] for r in g])} | {sum(1 for r in g if r['step'] == 0)}名 |"
        )
    w("")
    w("### 初回伴走のタイミング（SP開始から）")
    w("")
    w("| 初回伴走 | 人数 | STEP中央値 | STEP0 |")
    w("|---------|------|-----------|-------|")
    for label, pred in [
        ("SP+14日以内", lambda d: d is not None and d <= 14),
        ("SP+15〜24日", lambda d: d is not None and 15 <= d <= 24),
        ("SP+25日以降", lambda d: d is not None and d >= 25),
        ("伴走未", lambda d: d is None),
    ]:
        g = [r for r in all_rows if pred(r["coach_sp"])]
        w(
            f"| {label} | {len(g)}名 | {_median([r['step'] for r in g])} | "
            f"{sum(1 for r in g if r['step'] == 0)}名 |"
        )
    w("")
    if sa_coach_gaps:
        w("### 自己分析 → 初回伴走の間隔")
        w("")
        w(f"集計: 伴走日 ≧ 自己分析日 の **{len(sa_coach_gaps)}名**。")
        w("")
        w("| 間隔 | 人数 | STEP中央値 | STEP0 |")
        w("|------|------|-----------|-------|")
        for label, pred in [
            ("4〜7日", lambda g: 4 <= g <= 7),
            ("8〜14日", lambda g: 8 <= g <= 14),
            ("15〜21日", lambda g: 15 <= g <= 21),
            ("22日以上", lambda g: g >= 22),
        ]:
            g = [r for gap, r in sa_coach_gaps if pred(gap)]
            w(
                f"| {label} | {len(g)}名 | {_median([r['step'] for r in g])} | "
                f"{sum(1 for r in g if r['step'] == 0)}名 |"
            )
        w("")
        w(f"- **全体**: 中央値 **{_median(gaps_sc):.0f}日**")
    w("")
    w("---")
    w("")
    w(f"## 4. 相関係数（n={n}）")
    w("")
    w("| 変数ペア | r | n |")
    w("|---------|---|---|")
    for a, b, x, y in corr_pairs:
        r, nn = _corr(x, y)
        rs = f"{r:.2f}" if r is not None else "n/a"
        w(f"| {a} vs {b} | **{rs}** | {nn} |")
    w("")
    w("---")
    w("")
    w("## 5. 伴走セッションはSPを加速させるか？")
    w("")
    w("### SP期間中の伴走密度 vs SP完了")
    w("")
    w("| SP期間中の伴走 | 人数 | STEP中央値 | SP完了まで（中央値） |")
    w("|---------------|------|-----------|---------------------|")
    for label, pred in [
        ("0回", lambda c: c == 0),
        ("1〜2回", lambda c: 1 <= c <= 2),
        ("3回以上", lambda c: c >= 3),
    ]:
        g = [r for r in all_rows if pred(r["n_coach"])]
        w(
            f"| {label} | {len(g)}名 | {_median([r['step'] for r in g])} | "
            f"{_median([r['sp_days'] for r in g if r['sp_days']])} |"
        )
    w("")
    w("### 週次ペース vs SP完了速度")
    w("")
    w("| 週次ペース | SP完了中央値 | STEP中央値 |")
    w("|-----------|-------------|-----------|")
    for label, pred in [
        ("週次率 80%以上", lambda r: r["weekly_rate"] is not None and r["weekly_rate"] >= 0.8),
        ("週次率 50%未満", lambda r: r["weekly_rate"] is not None and r["weekly_rate"] < 0.5),
    ]:
        g = [r for r in all_rows if pred(r)]
        w(
            f"| {label} | {_median([r['sp_days'] for r in g if r['sp_days']])} | "
            f"{_median([r['step'] for r in g])} |"
        )
    w("")
    w("**総合**: 伴走は「SPを短く終わらせる加速器」より、**SPと並行・その後の継続サポート**。")
    w("")
    w("---")
    w("")
    w("## 6. 運用上の示唆")
    w("")
    w(f"1. **SP開始〜7日以内の自己分析** — {len(sa7)}名（{pct(len(sa7), n)}）。15日超はフォロー最優先")
    w("2. **自己分析後〜伴走までの空き** — 短縮が次のKPI")
    w("3. **伴走の回数より開始タイミング** — 早いSA×早い伴走でSTEPが最も高い")
    w("4. **週次ペース単独の警戒は不可** — `SA gap 14日超 & STEP5未満` を併用")
    w("5. **50日SP生徒はSTEP比較から除外**")
    w("")
    w("---")
    w("")
    w("## 7. 注意点・再集計")
    w("")
    w(f"- {snapshot}時点のスナップショット")
    w("- コミットプランQ列（SP開始）未入力が多い場合、SA gapはLステップSP開始で補完")
    w("- 相関は因果ではない")
    w("")
    w("```bash")
    w('cd "/Users/fuka/生徒分析/新特進_セッション分析"')
    w("python3 scripts/generate_session_sp_correlation_report.py")
    w("python3 scripts/render_session_gantt.py \\")
    w('  --commit-plan "$HOME/Downloads/コミットプラン 2026年6月3日集計.xlsx" \\')
    w("  --lstep data/metadata/lstep_tokushin_userpaste.tsv")
    w("```")
    w("")
    w("### 関連ファイル")
    w("")
    w("- タイムライン: `session_timeline_202604.html`（同フォルダ）")
    w("- 旧版（5/30）: `../session_vs_sp_correlation_202604.md`")

    main_path = out_dir / "session_vs_sp_correlation_202604.md"
    main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # SP30d supplement
    s30: list[str] = []
    s = s30.append
    s("# セッション × SP進行 相関分析（SP開始+30日以上コホート）")
    s("")
    s(f"**集計日**: {snapshot}  ")
    s(f"**母数**: **{n30}名** — SP開始から30日以上経過  ")
    s(f"**ベース**: 4月入会・新特進{n}名")
    s("")
    s(
        "> 全員分析は "
        "[`session_vs_sp_correlation_202604.md`](session_vs_sp_correlation_202604.md) を参照。"
    )
    s("")
    s("---")
    s("")
    s(f"## 38名→{n}名 / 除外")
    s("")
    if excluded30:
        s("| 除外 | SP開始 | 経過日数 |")
        s("|------|--------|---------|")
        for r in excluded30:
            s(f"| {r['name']} | {r['sp']} | +{r['days_since_sp']}日 |")
    else:
        s(f"全{n}名がSP+30日以上（除外0名）。")
    s("")
    s("## SA gap（SP+30日コホート）")
    s("")
    s30.extend(band_table(rows30, n30))
    s("")
    s("## SP完了（累積）")
    s("")
    s("| SP完了まで | 完了 | 母数中% | SA gap中央値 | SA 7日以内 |")
    s("|-----------|------|---------|-------------|-----------|")
    for t in [15, 20, 25, 30, 35, 40, 60]:
        grp = [r for r in rows30 if r["sp_days"] is not None and r["sp_days"] <= t]
        gaps = [r["sa_gap"] for r in grp if r["sa_gap"] is not None]
        sa7c = sum(1 for r in grp if r["sa_gap"] is not None and r["sa_gap"] <= 7)
        s(
            f"| {t}日以内 | {len(grp)}名 | {pct(len(grp), n30)} | {_median(gaps)} | {sa7c}/{len(grp) or 1} |"
        )
    nd30 = [r for r in rows30 if r["sp_days"] is None]
    s("")
    s(f"**SP未完了**: {len(nd30)}名")
    s("")
    s("## 相関（SP+30日）")
    s("")
    s("| 変数ペア | r | n |")
    s("|---------|---|---|")
    for a, b, x, y in [
        ("STEP", "SA gap", [r["step"] for r in rows30], [r["sa_gap"] for r in rows30]),
        ("STEP", "週次率", [r["step"] for r in rows30], [r["weekly_rate"] for r in rows30]),
        ("STEP", "伴走回数", [r["step"] for r in rows30], [r["n_coach"] for r in rows30]),
        ("SP完了日数", "SA gap", [r["sp_days"] for r in rows30], [r["sa_gap"] for r in rows30]),
    ]:
        r, nn = _corr(x, y)
        rs = f"{r:.2f}" if r is not None else "n/a"
        s(f"| {a} vs {b} | **{rs}** | {nn} |")
    s("")
    s("```bash")
    s("python3 scripts/analyze_cohort_sp30d.py \\")
    s('  "$HOME/Downloads/コミットプラン 2026年6月3日集計.xlsx" \\')
    s(f"  --snapshot {snapshot} \\")
    s("  --lstep-tsv data/metadata/lstep_tokushin_userpaste.tsv \\")
    s("  --min-days 30")
    s("```")

    sp30_path = out_dir / "session_vs_sp_correlation_202604_sp30d.md"
    sp30_path.write_text("\n".join(s30) + "\n", encoding="utf-8")

    print(f"Wrote {main_path}")
    print(f"Wrote {sp30_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
