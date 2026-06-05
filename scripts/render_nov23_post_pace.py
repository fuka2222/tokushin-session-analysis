#!/usr/bin/env python3
"""11月入会卒業者23名の月次投稿ペース — 表・グラフHTML出力"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from analyze_post_pace_100 import (
    BENCH_60_CUM,
    BENCH_80_CUM,
    BENCH_CUM,
    load_monthly_students,
    load_nov_graduates,
    pace_label,
)

MONTH_LABELS = ["0ヶ月", "1ヶ月", "2ヶ月", "3ヶ月", "4ヶ月", "5ヶ月", "6ヶ月"]


def pct_of_target(actual: float, target: float) -> float | None:
    if np.isnan(actual) or target <= 0:
        return None
    return round(actual / target * 100, 1)


def build_cohort_stats(merged: pd.DataFrame) -> list[dict]:
    stats = []
    for m in range(7):
        vals = []
        for cum in merged["cumulative"]:
            if m < len(cum) and not np.isnan(cum[m]):
                vals.append(cum[m])
        tgt = BENCH_CUM[m] if m < len(BENCH_CUM) else 100
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


def build_student_rows(merged: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in merged.sort_values("卒業時投稿数", ascending=False).iterrows():
        cum = r["cumulative"] if isinstance(r["cumulative"], list) else []
        monthly = r["monthly"] if isinstance(r["monthly"], list) else []
        month_data = []
        for m in range(7):
            c = cum[m] if m < len(cum) else np.nan
            mo = monthly[m] if m < len(monthly) else np.nan
            tgt = BENCH_CUM[m] if m < len(BENCH_CUM) else 100
            month_data.append(
                {
                    "cum": None if np.isnan(c) else int(c),
                    "monthly": None if np.isnan(mo) else int(mo),
                    "target": tgt,
                    "pct": pct_of_target(c, tgt),
                }
            )
        # latest month with data
        last_m = -1
        last_cum = np.nan
        for m in range(7):
            if m < len(cum) and not np.isnan(cum[m]):
                last_m = m
                last_cum = cum[m]
        tgt5 = BENCH_CUM[5]
        rows.append(
            {
                "name": r["生徒名"],
                "mg": r.get("mg") or r.get("担当MG") or "",
                "grad": int(r["卒業時投稿数"]),
                "grad_pct100": round(r["卒業時投稿数"] / 100 * 100, 1),
                "months": month_data,
                "m5_pct": pct_of_target(last_cum if last_m >= 5 else (cum[5] if len(cum) > 5 else np.nan), tgt5),
                "pace": pace_label(cum[5] if len(cum) > 5 else np.nan, tgt5),
            }
        )
    return rows


def render_html(stats: list[dict], students: list[dict], out_path: Path) -> None:
    data_json = json.dumps(
        {
            "stats": stats,
            "students": students,
            "bench_cum": BENCH_CUM,
            "bench_80_cum": BENCH_80_CUM,
            "bench_60_cum": BENCH_60_CUM,
        },
        ensure_ascii=False,
    )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>11月入会23名 — 月次投稿 vs 60/80/100投稿基準</title>
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
  .legend-inline {{ font-size: 12px; color: #555; margin-bottom: 12px; }}
</style>
</head>
<body>
<header>
  <h1>11月入会卒業者23名 — 月次投稿ペース vs 60/80/100投稿基準</h1>
  <p>
    <strong>100投稿:</strong> 0→17→35→56→78→100 ／
    <strong>80投稿:</strong> 0→13→27→44→62→80 ／
    <strong>60投稿:</strong> 0→10→21→34→47→60
    ／ データ: コミットプラン「新 月次投稿数」P列〜 ＋ 投稿数集計用2026年6月3日DL
  </p>
</header>
<main>
  <section id="summary-cards"></section>

  <section>
    <h2>コホート全体 — 基準値との比較（累計投稿数）</h2>
    <div class="legend-inline">折れ線: 100基準（赤）／ 80基準（橙）／ 60基準（灰）／ 23名中央値（青）／ 23名平均（緑破線）</div>
    <div class="charts">
      <div class="chart-box"><canvas id="chartCumulative"></canvas></div>
      <div class="chart-box"><canvas id="chartPct"></canvas></div>
    </div>
    <div class="scroll" style="margin-top:16px">
      <table id="cohortTable">
        <thead>
          <tr>
            <th>月</th><th>基準累計</th><th>データあり</th><th>基準達成人数</th><th>達成率</th>
            <th>中央値</th><th>平均</th><th>中央値÷基準</th><th>平均÷基準</th><th>最小</th><th>最大</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>生徒別 — 月次累計と基準達成率（%）</h2>
    <p class="note">セルは「累計（基準比%）」。100%以上=緑、50〜99%=黄、50%未満=赤。ー=未入力。</p>
    <div class="scroll">
      <table id="studentTable">
        <thead>
          <tr>
            <th>生徒名</th><th>MG</th><th>卒業時</th>
            <th>0ヶ月</th><th>1ヶ月</th><th>2ヶ月</th><th>3ヶ月</th><th>4ヶ月</th><th>5ヶ月</th><th>6ヶ月</th>
            <th>5ヶ月時判定</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>上位5名の経過（累計投稿数）</h2>
    <div class="chart-box" style="height:380px"><canvas id="chartTop5"></canvas></div>
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
  const pct = m.pct != null ? m.pct + '%' : '—';
  return `${{m.cum}}<br><small>(${{pct}})</small>`;
}}

// Summary cards
const grads = DATA.students.map(s => s.grad);
const avgGrad = (grads.reduce((a,b)=>a+b,0)/grads.length).toFixed(1);
const medGrad = [...grads].sort((a,b)=>a-b)[Math.floor(grads.length/2)];
const over100 = grads.filter(g=>g>=100).length;
document.getElementById('summary-cards').innerHTML = `
  <h2>サマリー</h2>
  <div class="summary-grid">
    <div class="card"><div class="label">対象人数</div><div class="value">23名</div></div>
    <div class="card"><div class="label">卒業時平均投稿数</div><div class="value">${{avgGrad}}本</div></div>
    <div class="card"><div class="label">卒業時中央値</div><div class="value">${{medGrad}}本</div></div>
    <div class="card"><div class="label">100投稿以上</div><div class="value">${{over100}}名</div></div>
  </div>`;

// Cohort table
const tbody = document.querySelector('#cohortTable tbody');
DATA.stats.forEach(s => {{
  if (s.n === 0) return;
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${{s.label}}</td><td>${{s.target}}</td><td>${{s.n}}</td>
    <td>${{s.on_track}}</td><td>${{s.on_track_pct}}%</td>
    <td>${{s.median}}</td><td>${{s.mean}}</td>
    <td class="${{cellClass(s.median_pct)}}">${{s.median_pct}}%</td>
    <td class="${{cellClass(s.mean_pct)}}">${{s.mean_pct}}%</td>
    <td>${{s.min}}</td><td>${{s.max}}</td>`;
  tbody.appendChild(tr);
}});

// Student table
const stbody = document.querySelector('#studentTable tbody');
DATA.students.forEach(s => {{
  const tr = document.createElement('tr');
  const cells = s.months.map(m => {{
    const cls = m.cum == null ? 'na' : cellClass(m.pct);
    return `<td class="${{cls}}">${{fmtCell(m)}}</td>`;
  }}).join('');
  tr.innerHTML = `
    <td class="name">${{s.name}}</td>
    <td class="mg">${{s.mg}}</td>
    <td><strong>${{s.grad}}</strong><br><small>(${{s.grad_pct100}}%)</small></td>
    ${{cells}}
    <td>${{s.pace}}</td>`;
  stbody.appendChild(tr);
}});

const statsWithData = DATA.stats.filter(s => s.n > 0);
const labels = statsWithData.map(s => s.label);
const medians = statsWithData.map(s => s.median);
const means = statsWithData.map(s => s.mean);

function benchSeries(bench) {{
  return statsWithData.map(s => bench[s.month] != null ? bench[s.month] : bench[bench.length - 1]);
}}

function medianPctSeries(bench) {{
  return statsWithData.map(s => {{
    const tgt = bench[s.month] != null ? bench[s.month] : bench[bench.length - 1];
    return tgt > 0 ? Math.round(s.median / tgt * 1000) / 10 : 100;
  }});
}}

const bench100 = benchSeries(DATA.bench_cum);
const bench80 = benchSeries(DATA.bench_80_cum);
const bench60 = benchSeries(DATA.bench_60_cum);

const commonOpts = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
}};

const benchLine = (label, data, color, width = 2, dash = []) => ({{
  label, data, borderColor: color, backgroundColor: color,
  borderWidth: width, borderDash: dash, pointRadius: 3, tension: 0.1, fill: false,
}});

new Chart(document.getElementById('chartCumulative'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [
      benchLine('100投稿基準', bench100, '#c0392b', 2.5),
      benchLine('80投稿基準', bench80, '#e67e22', 2, [4, 3]),
      benchLine('60投稿基準', bench60, '#7f8c8d', 2, [4, 3]),
      benchLine('23名 中央値', medians, '#2471a3', 2.5),
      benchLine('23名 平均', means, '#1e8449', 2, [5, 4]),
    ]
  }},
  options: {{ ...commonOpts, scales: {{ y: {{ title: {{ display: true, text: '累計投稿数（本）' }} }}, x: {{ title: {{ display: true, text: 'SP開始からの経過月' }} }} }} }}
}});

new Chart(document.getElementById('chartPct'), {{
  type: 'bar',
  data: {{
    labels,
    datasets: [
      {{ label: '中央値 ÷ 100基準', data: medianPctSeries(DATA.bench_cum), backgroundColor: '#c0392b' }},
      {{ label: '中央値 ÷ 80基準', data: medianPctSeries(DATA.bench_80_cum), backgroundColor: '#e67e22' }},
      {{ label: '中央値 ÷ 60基準', data: medianPctSeries(DATA.bench_60_cum), backgroundColor: '#7f8c8d' }},
    ]
  }},
  options: {{
    ...commonOpts,
    scales: {{
      y: {{ title: {{ display: true, text: '基準達成率（%）' }}, suggestedMax: 120, ticks: {{ callback: v => v+'%' }} }},
      x: {{ title: {{ display: true, text: '経過月' }} }}
    }}
  }}
}});

// Top 5 chart
const top5 = DATA.students.slice(0, 5);
const monthLabels = ['0ヶ月','1ヶ月','2ヶ月','3ヶ月','4ヶ月','5ヶ月','6ヶ月'];
const colors = ['#2471a3','#1e8449','#8e44ad','#d35400','#16a085'];
const topDatasets = top5.map((s,i) => ({{
  label: s.name + ' (' + s.grad + '本)',
  data: s.months.map(m => m.cum),
  borderColor: colors[i],
  backgroundColor: colors[i],
  spanGaps: false,
  tension: 0.15,
  pointRadius: 3,
}}));
const benchFull = (bench, finalVal) => bench.concat([finalVal != null ? finalVal : bench[bench.length - 1]]);
[
  {{ label: '100投稿基準', data: benchFull(DATA.bench_cum, 100), color: '#c0392b' }},
  {{ label: '80投稿基準', data: benchFull(DATA.bench_80_cum, 80), color: '#e67e22' }},
  {{ label: '60投稿基準', data: benchFull(DATA.bench_60_cum, 60), color: '#7f8c8d' }},
].forEach(b => topDatasets.unshift({{
  label: b.label,
  data: b.data,
  borderColor: b.color,
  borderWidth: 2,
  borderDash: [6, 4],
  pointRadius: 0,
  tension: 0,
}}));

new Chart(document.getElementById('chartTop5'), {{
  type: 'line',
  data: {{ labels: monthLabels, datasets: topDatasets }},
  options: {{ ...commonOpts, scales: {{ y: {{ title: {{ display: true, text: '累計投稿数（本）' }} }}, x: {{ title: {{ display: true, text: '経過月' }} }} }} }}
}});
</script>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")


def export_json(stats: list[dict], students: list[dict], out_path: Path) -> None:
    payload = {
        "generatedAt": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "cohortLabel": "11月入会卒業者",
        "studentCount": len(students),
        "benchCum100": BENCH_CUM,
        "benchCum80": BENCH_80_CUM,
        "benchCum60": BENCH_60_CUM,
        "stats": stats,
        "students": students,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "reports" / "nov23_post_pace.html",
    )
    parser.add_argument(
        "--joes-out",
        type=Path,
        default=Path("/Users/fuka/01_AI/advances-course-task/src/data/nov23-post-pace.json"),
        help="ジョーズくん用 JSON 出力先",
    )
    args = parser.parse_args()

    students = load_monthly_students(args.commit_plan)
    nov = load_nov_graduates(args.posts)
    merged = nov.merge(students, on="name_norm", how="left")

    stats = build_cohort_stats(merged)
    rows = build_student_rows(merged)
    render_html(stats, rows, args.out)
    export_json(stats, rows, args.joes_out)

    print(f"Report: {args.out}")
    print(f"Joes JSON: {args.joes_out}")
    print("\n=== コホート vs 基準（累計） ===")
    for s in stats:
        if s["n"] == 0:
            continue
        print(
            f"  {s['label']}: 基準{s['target']} / 中央値{s['median']} ({s['median_pct']}%) "
            f"/ 平均{s['mean']} ({s['mean_pct']}%) / 達成{s['on_track']}/{s['n']}"
        )


if __name__ == "__main__":
    main()
