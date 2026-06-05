#!/usr/bin/env python3
"""
毎月コミット分析レポート（①卒業投稿数 ②月次ペース ③初投稿30日）

入力（Downloads 想定）:
  - 投稿数集計用*.xlsx
  - コミットプラン (N).xlsx
  - Lステップの顧客データ*.xlsx

出力: data/reports/monthly_YYYYMMDD/
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_post_pace_100 import (
    BENCH_60_CUM,
    BENCH_80_CUM,
    BENCH_CUM,
    load_monthly_students,
    load_nov_graduates,
    norm_name,
    pace_label,
    parse_val,
)
from first_post_30d_report import (
    compute_first_post_30d,
    format_markdown as format_30d_md,
    rate_rows_to_df,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POSTS = Path.home() / "Downloads" / "投稿数集計用2026年6月3日DL.xlsx"
DEFAULT_COMMIT = Path.home() / "Downloads" / "コミットプラン (9).xlsx"
DEFAULT_LSTEP = Path.home() / "Downloads" / "Lステップの顧客データ 2026年6月3日集計.xlsx"

GRAD_SHEET = "コミット11月入会卒業者リスト"
MONTH_LABELS = ["0ヶ月", "1ヶ月", "2ヶ月", "3ヶ月", "4ヶ月", "5ヶ月", "6ヶ月"]


def load_commit_graduates(posts_path: Path) -> pd.DataFrame:
    """11月入会卒業者23名（中途解約2名除外）。"""
    return load_nov_graduates(posts_path)


def load_ideal_targets(commit_path: Path) -> tuple[list[float], list[float]]:
    """新 月次投稿数 シート row7=累計120目標, row8=単月目標。"""
    raw = pd.read_excel(commit_path, sheet_name="新 月次投稿数", header=None)
    cum = [parse_val(raw.iloc[7, c]) for c in range(15, 22)]
    monthly = [parse_val(raw.iloc[8, c]) for c in range(15, 22)]
    cum = [0.0 if np.isnan(v) else float(v) for v in cum]
    monthly = [0.0 if np.isnan(v) else float(v) for v in monthly]
    return monthly, cum


def pct_of_target(actual: float, target: float) -> float | None:
    if np.isnan(actual) or target <= 0:
        return None
    return round(actual / target * 100, 1)


def _fill_monthly_by_fuzzy(merged: pd.DataFrame, monthly_all: pd.DataFrame) -> pd.DataFrame:
    """照合用名前の表記ゆれを部分一致で補完。"""
    by_norm = {r["name_norm"]: r for _, r in monthly_all.iterrows()}
    for i, row in merged.iterrows():
        if pd.notna(row.get("mg")) or _as_list(row.get("monthly")):
            continue
        key = row["name_norm"]
        hit = by_norm.get(key)
        if hit is None:
            for nk, r in by_norm.items():
                if key in nk or nk in key:
                    hit = r
                    break
        if hit is None:
            continue
        for col in ("mg", "monthly", "cumulative", "status", "grad_posts_sheet"):
            if col in hit.index:
                merged.at[i, col] = hit[col]
    return merged


def _as_list(val) -> list:
    if isinstance(val, list):
        return val
    return []


def build_cohort_stats_merged(merged: pd.DataFrame, bench_cum: list[float]) -> list[dict]:
    stats = []
    for m in range(7):
        vals = []
        for cum in merged["cumulative"]:
            cum = _as_list(cum)
            if m < len(cum) and not np.isnan(cum[m]):
                vals.append(cum[m])
        tgt = bench_cum[m] if m < len(bench_cum) else bench_cum[-1]
        if not vals:
            stats.append({"month": m, "label": MONTH_LABELS[m], "target": tgt, "n": 0})
            continue
        arr = np.array(vals)
        on = int((arr >= tgt).sum())
        med = float(np.median(arr))
        stats.append(
            {
                "month": m,
                "label": MONTH_LABELS[m],
                "target": tgt,
                "n": len(vals),
                "on_track": on,
                "on_track_pct": round(on / len(vals) * 100, 1),
                "median": round(med, 1),
                "mean": round(float(arr.mean()), 1),
                "min": round(float(arr.min()), 1),
                "max": round(float(arr.max()), 1),
                "median_pct": round(med / tgt * 100, 1) if tgt > 0 else 100,
                "mean_pct": round(float(arr.mean()) / tgt * 100, 1) if tgt > 0 else 100,
            }
        )
    return stats


def build_student_rows_merged(
    merged: pd.DataFrame, bench_cum: list[float], grad_target: float = 120.0
) -> list[dict]:
    rows = []
    for _, r in merged.sort_values("卒業時投稿数", ascending=False).iterrows():
        cum = _as_list(r.get("cumulative"))
        monthly = _as_list(r.get("monthly"))
        month_data = []
        for m in range(7):
            c = cum[m] if m < len(cum) else np.nan
            mo = monthly[m] if m < len(monthly) else np.nan
            tgt = bench_cum[m] if m < len(bench_cum) else bench_cum[-1]
            month_data.append(
                {
                    "cum": None if np.isnan(c) else int(c),
                    "monthly": None if np.isnan(mo) else int(mo),
                    "target": tgt,
                    "pct": pct_of_target(c, tgt),
                }
            )
        m5 = cum[5] if len(cum) > 5 else np.nan
        tgt5 = bench_cum[5] if len(bench_cum) > 5 else bench_cum[-1]
        grad = int(r["卒業時投稿数"])
        rows.append(
            {
                "name": r["生徒名"],
                "mg": r.get("mg") or r.get("担当MG") or r.get("担当MG名") or "",
                "grad": grad,
                "grad_pct120": round(grad / grad_target * 100, 1),
                "months": month_data,
                "m5_pct": pct_of_target(m5, tgt5),
                "pace": pace_label(m5, tgt5),
            }
        )
    return rows


def render_monthly_html(
    *,
    title: str,
    subtitle: str,
    stats: list[dict],
    students: list[dict],
    bench_cum: list[float],
    bench_80_cum: list[float],
    bench_60_cum: list[float],
    ideal_cum: list[float],
    ideal_monthly: list[float],
    out_path: Path,
) -> None:
    data_json = json.dumps(
        {
            "title": title,
            "subtitle": subtitle,
            "stats": stats,
            "students": students,
            "bench_cum": bench_cum,
            "bench_80_cum": bench_80_cum,
            "bench_60_cum": bench_60_cum,
            "ideal_cum": ideal_cum,
            "ideal_monthly": ideal_monthly,
        },
        ensure_ascii=False,
    )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif; margin: 0; background: #f4f4f4; color: #222; }}
  header {{ background: #fff; border-bottom: 1px solid #ddd; padding: 18px 24px; }}
  header h1 {{ margin: 0 0 6px; font-size: 20px; }}
  header p {{ margin: 0; font-size: 13px; color: #555; line-height: 1.5; }}
  main {{ padding: 20px 24px 40px; max-width: 1400px; margin: 0 auto; }}
  section {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }}
  h2 {{ margin: 0 0 14px; font-size: 16px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ position: relative; height: 340px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: center; }}
  th {{ background: #eef2f7; font-weight: 600; }}
  td.name {{ text-align: left; white-space: nowrap; }}
  td.mg {{ text-align: left; font-size: 11px; color: #444; }}
  .ok {{ background: #e2efda; color: #1e5631; font-weight: 600; }}
  .warn {{ background: #fff2cc; color: #7f6000; }}
  .bad {{ background: #fce4d6; color: #833c0c; }}
  .na {{ color: #aaa; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  .card {{ background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; }}
  .card .label {{ font-size: 11px; color: #666; }}
  .card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  .scroll {{ overflow-x: auto; }}
  .note {{ font-size: 12px; color: #666; line-height: 1.6; margin-top: 10px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<main>
  <section id="summary-cards"></section>
  <section>
    <h2>コホート全体 — 理想120累計・100/80/60基準との比較</h2>
    <div class="charts">
      <div class="chart-box"><canvas id="chartCumulative"></canvas></div>
      <div class="chart-box"><canvas id="chartPct"></canvas></div>
    </div>
    <div class="scroll" style="margin-top:16px"><table id="cohortTable"><thead>
      <tr><th>月</th><th>理想累計</th><th>データあり</th><th>理想達成</th><th>達成率</th>
      <th>中央値</th><th>平均</th><th>中央値÷理想</th><th>平均÷理想</th></tr>
    </thead><tbody></tbody></table></div>
  </section>
  <section>
    <h2>生徒別 — 月次累計と理想比（%）</h2>
    <p class="note">セル: 累計（理想比%）。100%+=緑 / 50-99%=黄 / 50%未満=赤</p>
    <div class="scroll"><table id="studentTable"><thead>
      <tr><th>生徒名</th><th>MG</th><th>卒業時</th>
      <th>0ヶ月</th><th>1ヶ月</th><th>2ヶ月</th><th>3ヶ月</th><th>4ヶ月</th><th>5ヶ月</th><th>6ヶ月</th>
      <th>5ヶ月判定</th></tr>
    </thead><tbody></tbody></table></div>
  </section>
  <section>
    <h2>月次単月投稿数（実績 vs 理想単月）</h2>
    <div class="chart-box" style="height:360px"><canvas id="chartMonthly"></canvas></div>
  </section>
</main>
<script>
const DATA = {data_json};
function cellClass(pct) {{
  if (pct == null) return 'na';
  if (pct >= 100) return 'ok';
  if (pct >= 50) return 'warn';
  return 'bad';
}}
function fmtCell(m) {{
  if (m.cum == null) return '<span class="na">—</span>';
  return `${{m.cum}}<br><small>(${{m.pct != null ? m.pct+'%' : '—'}})</small>`;
}}
const n = DATA.students.length;
const grads = DATA.students.map(s => s.grad);
const avgGrad = (grads.reduce((a,b)=>a+b,0)/n).toFixed(1);
const sorted = [...grads].sort((a,b)=>a-b);
const medGrad = sorted[Math.floor(n/2)];
document.getElementById('summary-cards').innerHTML = `
  <h2>サマリー</h2><div class="summary-grid">
  <div class="card"><div class="label">対象</div><div class="value">${{n}}名</div></div>
  <div class="card"><div class="label">卒業時平均</div><div class="value">${{avgGrad}}本</div></div>
  <div class="card"><div class="label">卒業時中央値</div><div class="value">${{medGrad}}本</div></div>
  <div class="card"><div class="label">120本以上</div><div class="value">${{grads.filter(g=>g>=120).length}}名</div></div>
  </div>`;
const tbody = document.querySelector('#cohortTable tbody');
DATA.stats.forEach(s => {{
  if (!s.n) return;
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${{s.label}}</td><td>${{s.target}}</td><td>${{s.n}}</td>
    <td>${{s.on_track}}</td><td>${{s.on_track_pct}}%</td><td>${{s.median}}</td><td>${{s.mean}}</td>
    <td class="${{cellClass(s.median_pct)}}">${{s.median_pct}}%</td>
    <td class="${{cellClass(s.mean_pct)}}">${{s.mean_pct}}%</td>`;
  tbody.appendChild(tr);
}});
const stbody = document.querySelector('#studentTable tbody');
DATA.students.forEach(s => {{
  const cells = s.months.map(m => `<td class="${{m.cum==null?'na':cellClass(m.pct)}}">${{fmtCell(m)}}</td>`).join('');
  stbody.innerHTML += `<tr><td class="name">${{s.name}}</td><td class="mg">${{s.mg}}</td>
    <td><strong>${{s.grad}}</strong><br><small>(${{s.grad_pct120}}%)</small></td>${{cells}}<td>${{s.pace}}</td></tr>`;
}});
const statsWith = DATA.stats.filter(s => s.n > 0);
const labels = statsWith.map(s => s.label);
const line = (label, data, color, dash=[]) => ({{
  label, data, borderColor: color, borderWidth: 2, borderDash: dash, tension: 0.1, pointRadius: 3, fill: false
}});
new Chart(document.getElementById('chartCumulative'), {{
  type: 'line',
  data: {{ labels, datasets: [
    line('理想120累計', statsWith.map(s => DATA.ideal_cum[s.month] ?? DATA.ideal_cum.at(-1)), '#8e44ad', [6,3]),
    line('100基準', statsWith.map(s => DATA.bench_cum[s.month] ?? 100), '#c0392b'),
    line('80基準', statsWith.map(s => DATA.bench_80_cum[s.month] ?? 80), '#e67e22', [4,3]),
    line('中央値', statsWith.map(s => s.median), '#2471a3'),
    line('平均', statsWith.map(s => s.mean), '#1e8449', [5,4]),
  ]}},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom' }} }} }}
}});
new Chart(document.getElementById('chartPct'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{
    label: '中央値÷理想120', data: statsWith.map(s => {{
      const t = DATA.ideal_cum[s.month] ?? 1; return t>0 ? Math.round(s.median/t*1000)/10 : 100;
    }}), backgroundColor: '#8e44ad'
  }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, scales: {{ y: {{ ticks: {{ callback: v => v+'%' }} }} }} }}
}});
// 単月: コホート平均 vs 理想
const monthAvgs = [];
for (let m=0; m<7; m++) {{
  const vals = DATA.students.map(s => s.months[m]?.monthly).filter(v => v != null);
  monthAvgs.push(vals.length ? vals.reduce((a,b)=>a+b,0)/vals.length : null);
}}
new Chart(document.getElementById('chartMonthly'), {{
  type: 'bar',
  data: {{ labels: ['0ヶ月','1ヶ月','2ヶ月','3ヶ月','4ヶ月','5ヶ月','6ヶ月'], datasets: [
    {{ label: 'コホート平均（単月）', data: monthAvgs, backgroundColor: '#2471a3' }},
    {{ label: '理想単月', data: DATA.ideal_monthly, backgroundColor: '#d35400' }},
  ]}},
  options: {{ responsive: true, maintainAspectRatio: false }}
}});
</script>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")


GOAL_THRESHOLDS = [
    (60, "60投稿（コミット基準・半年目安）"),
    (80, "80投稿"),
    (100, "100投稿（新・半年目標）"),
    (120, "120投稿（理想・コミットプラン）"),
]

TIER_BREAKS = [
    (60, None, "60本以上 — 目標達成"),
    (31, 59, "31〜59本"),
    (1, 30, "1〜30本"),
    (0, 0, "0本"),
]


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def build_graduation_summary(grads: pd.DataFrame) -> dict:
    posts = grads["卒業時投稿数"].astype(int)
    n = len(grads)
    goals = []
    for threshold, label in GOAL_THRESHOLDS:
        hit = int((posts >= threshold).sum())
        goals.append(
            {
                "threshold": threshold,
                "label": label,
                "count": hit,
                "pct": _pct(hit, n),
                "miss": n - hit,
            }
        )
    tiers = []
    for lo, hi, label in TIER_BREAKS:
        if hi is None:
            mask = posts >= lo
        elif lo == hi == 0:
            mask = posts == 0
        else:
            mask = (posts >= lo) & (posts <= hi)
        cnt = int(mask.sum())
        tiers.append({"label": label, "lo": lo, "hi": hi, "count": cnt, "pct": _pct(cnt, n)})
    return {
        "n": n,
        "mean": round(float(posts.mean()), 1),
        "median": round(float(posts.median()), 1),
        "min": int(posts.min()),
        "max": int(posts.max()),
        "goals": goals,
        "tiers": tiers,
    }


def _goal_summary_lines(summary: dict) -> list[str]:
    n = summary["n"]
    g60 = next(g for g in summary["goals"] if g["threshold"] == 60)
    g100 = next(g for g in summary["goals"] if g["threshold"] == 100)
    lines = [
        "## 全体の把握（ひと目で）",
        "",
        f"**{n}名**の卒業者のうち、",
        f"- **{g60['count']}名（{g60['pct']}%）** が **60投稿** の目標に到達",
        f"- **{g100['count']}名（{g100['pct']}%）** が **100投稿** の新目標に到達",
        f"- 未達はそれぞれ **{g60['miss']}名（{round(100 - g60['pct'], 1)}%）** / **{g100['miss']}名（{round(100 - g100['pct'], 1)}%）**",
        "",
        f"平均 **{summary['mean']}本**・中央値 **{summary['median']}本**（最少 {summary['min']} / 最多 {summary['max']}）",
        "",
        "### 目標別 — 全体の何%が達成したか",
        "",
        "| 目標 | 達成人数 | 全体のうち | 未達 |",
        "|------|----------|------------|------|",
    ]
    for g in summary["goals"]:
        lines.append(
            f"| **{g['label']}** | {g['count']}名 | **{g['pct']}%** | {g['miss']}名（{round(100 - g['pct'], 1)}%） |"
        )
    lines += [
        "",
        "### 投稿数の層（内訳）",
        "",
        "| 区分 | 人数 | 全体のうち |",
        "|------|------|------------|",
    ]
    for t in summary["tiers"]:
        lines.append(f"| {t['label']} | {t['count']}名 | **{t['pct']}%** |")
    lines.append("")
    return lines


def _tier_divider_row(threshold: int, summary: dict) -> str | None:
    for g in summary["goals"]:
        if g["threshold"] == threshold:
            return (
                f"| — | **▼ {threshold}投稿以上（{g['count']}名・{g['pct']}%）** | — | — | — |"
            )
    return None


def render_graduation_summary_html(summary: dict, grads: pd.DataFrame, out_path: Path) -> None:
    g60 = next(g for g in summary["goals"] if g["threshold"] == 60)
    g100 = next(g for g in summary["goals"] if g["threshold"] == 100)
    goal_bars = "".join(
        f"""
        <div class="bar-row">
          <div class="bar-label">{g['label']}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{g['pct']}%"></div></div>
          <div class="bar-num"><strong>{g['count']}</strong>名 / {summary['n']}名（<strong>{g['pct']}%</strong>）</div>
        </div>"""
        for g in summary["goals"]
    )
    tier_rows = "".join(
        f"<tr><td>{t['label']}</td><td>{t['count']}名</td><td><strong>{t['pct']}%</strong></td></tr>"
        for t in summary["tiers"]
    )
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>11月入会卒業者23名 — 卒業時投稿数サマリー</title>
<style>
body{{font-family:"Hiragino Sans",Meiryo,sans-serif;margin:0;background:#f4f4f4;color:#222}}
header{{background:#fff;border-bottom:1px solid #ddd;padding:20px 24px}}
main{{max-width:900px;margin:0 auto;padding:24px}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:20px}}
h1{{margin:0 0 8px;font-size:22px}}
.lead{{font-size:18px;line-height:1.6;margin:0}}
.lead strong{{color:#1a5276}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}}
.card{{background:#f9f9f9;border:1px solid #e0e0e0;border-radius:6px;padding:14px;text-align:center}}
.card .v{{font-size:28px;font-weight:700;color:#1a5276}}
.card .l{{font-size:12px;color:#666;margin-top:4px}}
.bar-row{{display:grid;grid-template-columns:200px 1fr 140px;gap:10px;align-items:center;margin:10px 0;font-size:13px}}
.bar-track{{height:22px;background:#eee;border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;background:linear-gradient(90deg,#2980b9,#1a5276)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #ccc;padding:8px;text-align:center}}
th{{background:#eef2f7}}
td.name{{text-align:left}}
</style></head><body>
<header>
  <h1>11月入会卒業者 — 卒業時投稿数（23名）</h1>
  <p class="lead">全体の <strong>{g60['pct']}%</strong>（{g60['count']}名）が <strong>60投稿</strong> に到達。
  <strong>100投稿</strong> は <strong>{g100['pct']}%</strong>（{g100['count']}名）。</p>
  <div class="cards">
    <div class="card"><div class="v">{summary['mean']}</div><div class="l">平均（本）</div></div>
    <div class="card"><div class="v">{summary['median']}</div><div class="l">中央値（本）</div></div>
    <div class="card"><div class="v">{g60['pct']}%</div><div class="l">60投稿達成率</div></div>
  </div>
</header>
<main>
  <section><h2>目標別 — 全体の何%が達成したか</h2>{goal_bars}</section>
  <section><h2>投稿数の層</h2>
    <table><thead><tr><th>区分</th><th>人数</th><th>割合</th></tr></thead>
    <tbody>{tier_rows}</tbody></table>
  </section>
  <section><h2>生徒一覧（多い順）</h2>
    <table><thead><tr><th>順位</th><th>生徒名</th><th>投稿数</th><th>60目標</th><th>100目標</th></tr></thead><tbody>
"""
    for i, (_, r) in enumerate(grads.iterrows(), 1):
        p = int(r["卒業時投稿数"])
        ok60 = "✓" if p >= 60 else "—"
        ok100 = "✓" if p >= 100 else "—"
        html += f"<tr><td>{i}</td><td class='name'>{r['生徒名']}</td><td><strong>{p}</strong></td><td>{ok60}</td><td>{ok100}</td></tr>\n"
    html += "</tbody></table></section></main></body></html>"
    out_path.write_text(html, encoding="utf-8")


def write_graduation_section(grads: pd.DataFrame, out_dir: Path) -> str:
    summary = build_graduation_summary(grads)
    lines = [
        "# ① コミット11月入会卒業者 — 卒業時投稿数",
        "",
        f"- **対象**: `{GRAD_SHEET}`（**中途解約除外**: こしのあきこ、いわかわのぶゆき）",
        f"- **人数**: {summary['n']}名",
        "- **注**: 初投稿日・SP開始からの日数は2026-04-11以降入会向けのため、本コホート（11月入会卒業者）には含めない",
        "",
    ]
    lines.extend(_goal_summary_lines(summary))
    lines += [
        "## 生徒別（投稿数多い順）",
        "",
        "| 順位 | 生徒名 | 卒業時投稿数 | 担当MG | 入会後の説明実施日 |",
        "|------|--------|-------------|--------|-------------------|",
    ]
    for i, (_, r) in enumerate(grads.iterrows(), 1):
        p = int(r["卒業時投稿数"])
        if p < 60 and (i == 1 or int(grads.iloc[i - 2]["卒業時投稿数"]) >= 60):
            div = _tier_divider_row(60, summary)
            if div:
                lines.append(div)
        if p < 31 and (i == 1 or int(grads.iloc[i - 2]["卒業時投稿数"]) >= 31):
            n31 = int((grads["卒業時投稿数"] >= 31).sum())
            lines.append(
                f"| — | **▼ 31投稿以上（{n31}名・{_pct(n31, summary['n'])}%）** | — | — | — |"
            )
        mg = r.get("担当MG") or ""
        if pd.isna(mg):
            mg = ""
        enroll = r.get("入会後の説明実施日")
        enroll_s = pd.to_datetime(enroll).strftime("%Y-%m-%d") if pd.notna(enroll) else ""
        lines.append(f"| {i} | {r['生徒名']} | {p} | {mg} | {enroll_s} |")

    cols = ["生徒名", "入会後の説明実施日", "卒業時投稿数", "担当MG"]
    grads[cols].to_csv(out_dir / "commit_graduation_posts.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summary["goals"]).to_csv(
        out_dir / "graduation_goal_rates.csv", index=False, encoding="utf-8-sig"
    )
    render_graduation_summary_html(summary, grads, out_dir / "graduation_posts_summary.html")
    return "\n".join(lines) + "\n"


def run_report(
    *,
    posts_path: Path,
    commit_path: Path,
    lstep_path: Path,
    out_dir: Path,
    cohort_year: int,
    cohort_month: int,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now().strftime("%Y%m%d")

    # ①
    grads = load_commit_graduates(posts_path)
    sec1 = write_graduation_section(grads, out_dir)

    # ②
    monthly_all = load_monthly_students(commit_path)
    ideal_monthly, ideal_cum = load_ideal_targets(commit_path)
    merged = grads.merge(monthly_all, on="name_norm", how="left")
    merged = _fill_monthly_by_fuzzy(merged, monthly_all)
    missing = merged[merged["mg"].isna() & merged["monthly"].isna()]
    if len(missing):
        print(f"  警告: 月次データ未突合 {len(missing)}名 → {missing['生徒名'].tolist()}")

    stats = build_cohort_stats_merged(merged, ideal_cum)
    student_rows = build_student_rows_merged(merged, ideal_cum, grad_target=120.0)

    render_monthly_html(
        title=f"11月入会卒業者{len(grads)}名（中途解約除外）— 月次投稿 vs 理想ペース",
        subtitle=(
            f"理想120累計: {ideal_cum} ／ 理想単月: {ideal_monthly} ／ "
            f"100基準: {BENCH_CUM} ／ データ: {commit_path.name} + {posts_path.name}"
        ),
        stats=stats,
        students=student_rows,
        bench_cum=BENCH_CUM,
        bench_80_cum=BENCH_80_CUM,
        bench_60_cum=BENCH_60_CUM,
        ideal_cum=ideal_cum,
        ideal_monthly=ideal_monthly,
        out_path=out_dir / "commit_monthly_pace.html",
    )
    merged.to_csv(out_dir / "commit_monthly_merged.csv", index=False, encoding="utf-8-sig")

    sec2 = [
        "# ② 月次投稿ペース（コミット卒業者）",
        "",
        f"- 対象: ①と同じ {len(grads)}名",
        f"- 月次: コミットプラン `新 月次投稿数` P〜V列（0〜6ヶ月目）",
        f"- 理想累計（シートrow7）: {ideal_cum}",
        f"- 理想単月（シートrow8）: {ideal_monthly}",
        "",
        "| 月 | 理想累計 | データあり | 理想達成 | 達成率 | 中央値 | 平均 |",
        "|----|---------|-----------|---------|-------|-------|------|",
    ]
    for s in stats:
        if s.get("n", 0) == 0:
            continue
        sec2.append(
            f"| {s['label']} | {s['target']} | {s['n']} | {s['on_track']} | {s['on_track_pct']}% | "
            f"{s['median']} | {s['mean']} |"
        )
    sec2.append(f"\n詳細HTML: `commit_monthly_pace.html`\n")

    # ③
    fp30 = compute_first_post_30d(lstep_path, year=cohort_year, month=cohort_month)
    sec3 = format_30d_md(fp30)
    rate_rows_to_df(fp30["new_program"], "新").to_csv(
        out_dir / "first_post_30d_by_course.csv", index=False, encoding="utf-8-sig"
    )

    # 30d HTML snippet
    fp30_html = _render_30d_html(fp30, cohort_year, cohort_month)
    (out_dir / "first_post_30d.html").write_text(fp30_html, encoding="utf-8")

    index = "\n".join(
        [
            f"# 月次コミット分析レポート ({tag})",
            "",
            f"生成: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "## 出力ファイル",
            "",
            "- `graduation_posts_summary.html` — ①達成率・層別（見やすいサマリー）",
        "- `graduation_goal_rates.csv` — ①目標別達成率",
        "- `commit_graduation_posts.csv` — ①生徒別卒業投稿数",
            "- `commit_monthly_pace.html` — ②グラフ・表",
            "- `commit_monthly_merged.csv` — ②マージデータ",
            "- `first_post_30d_by_course.csv` — ③コース別",
            "- `first_post_30d.html` — ③表",
            "",
            sec1,
            "\n".join(sec2),
            sec3,
        ]
    )
    index_path = out_dir / "README.md"
    index_path.write_text(index, encoding="utf-8")
    return index_path


def _render_30d_html(result: dict, year: int, month: int) -> str:
    def table_rows(rows) -> str:
        trs = []
        for r in rows:
            trs.append(
                f"<tr><td>{r.course}</td><td>{r.denominator}</td>"
                f"<td>{r.completed}</td><td>{r.completion_rate_pct}%</td>"
                f"<td>{r.within_30}</td><td>{r.within_30_rate_pct}%</td></tr>"
            )
        return "\n".join(trs)

    new_all = result["new_program"][0]
    gap = result.get("target_gap_pct", 0)
    gap_note = "目標達成" if gap <= 0 else f"あと{gap}pt"
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>初投稿30日完了率 {year}年{month}月（新PG）</title>
<style>
body{{font-family:sans-serif;margin:24px;max-width:960px}}
table{{border-collapse:collapse;width:100%;margin-top:16px}}
th,td{{border:1px solid #ccc;padding:8px;text-align:center}} th{{background:#eef2f7}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}}
.card{{background:#f9f9f9;border:1px solid #ddd;border-radius:8px;padding:16px;text-align:center}}
.card .v{{font-size:28px;font-weight:bold}} .card .l{{font-size:12px;color:#666;margin-top:6px}}
.ok{{color:#1e8449}} .ng{{color:#c0392b}}
</style></head><body>
<h1>30日以内初投稿作成完了率（{year}年{month}月）</h1>
<p>集計対象: <strong>新プログラムのみ</strong>（STEP1完了月=分母 / STEP18完了=分子）</p>
<div class="cards">
  <div class="card"><div class="v">{result['target_rate_pct']}%</div><div class="l">目標</div></div>
  <div class="card"><div class="v {'ok' if result['overall_within_30_rate_pct'] >= result['target_rate_pct'] else 'ng'}">{result['overall_within_30_rate_pct']}%</div>
    <div class="l">結果（30日以内）<br>{new_all.within_30}/{new_all.denominator}名</div></div>
  <div class="card"><div class="v">{gap_note}</div><div class="l">目標との差（{gap:+.1f}pt）</div></div>
</div>
<h2>コース別</h2>
<table><thead><tr><th>コース</th><th>分母</th><th>完了</th><th>完了率</th>
<th>30日以内</th><th>30日以内率</th></tr></thead><tbody>
{table_rows(result['new_program'])}
</tbody></table>
</body></html>"""


def main() -> int:
    p = argparse.ArgumentParser(description="毎月コミット分析（①②③）")
    p.add_argument("--posts", type=Path, default=DEFAULT_POSTS)
    p.add_argument("--commit-plan", type=Path, default=DEFAULT_COMMIT)
    p.add_argument("--lstep", type=Path, default=DEFAULT_LSTEP)
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--cohort-year", type=int, default=2026)
    p.add_argument("--cohort-month", type=int, default=4, help="③初投稿30日の対象月")
    args = p.parse_args()

    for path, label in [
        (args.posts, "投稿数集計用"),
        (args.commit_plan, "コミットプラン"),
        (args.lstep, "Lステップ"),
    ]:
        if not path.exists():
            raise SystemExit(f"{label} がありません: {path}")

    out_dir = args.out_dir or (ROOT / "data" / "reports" / f"monthly_{datetime.now():%Y%m%d}")
    index = run_report(
        posts_path=args.posts,
        commit_path=args.commit_plan,
        lstep_path=args.lstep,
        out_dir=out_dir,
        cohort_year=args.cohort_year,
        cohort_month=args.cohort_month,
    )

    grads = load_commit_graduates(args.posts)
    summ = build_graduation_summary(grads)
    g60 = next(g for g in summ["goals"] if g["threshold"] == 60)
    print("=== ① コミット卒業時投稿数 ===")
    print(f"  人数: {summ['n']}")
    print(f"  60投稿達成: {g60['count']}名 ({g60['pct']}%)")
    print(f"  平均: {summ['mean']}")
    print("\n  上位5名:")
    for _, r in grads.head(5).iterrows():
        print(f"    {r['生徒名']}: {int(r['卒業時投稿数'])}本")

    fp = compute_first_post_30d(args.lstep, year=args.cohort_year, month=args.cohort_month)
    new_all = fp["new_program"][0]
    print(f"\n=== ③ 初投稿30日（{args.cohort_year}年{args.cohort_month}月・新PGのみ）===")
    print(f"  目標: {fp['target_rate_pct']}%")
    print(
        f"  結果: {fp['overall_within_30_rate_pct']}% "
        f"({new_all.within_30}/{new_all.denominator}名)"
    )
    print(f"  目標との差: {fp.get('target_gap_pct', 0):+.1f}pt")

    print(f"\nレポート: {index}")
    print(f"HTML: {out_dir / 'commit_monthly_pace.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
