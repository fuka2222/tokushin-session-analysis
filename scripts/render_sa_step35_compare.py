#!/usr/bin/env python3
"""仮説A: STEP3-5 × 自己分析 — SA受講済/未・タイミング別の比較グラフHTMLを生成。"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
from pathlib import Path

import pandas as pd

from analyze_commit_plan_cohort import load_students
from lstep_sp_lookup import build_lstep_index, lookup_lstep, norm_name

ROOT = Path(__file__).resolve().parent.parent
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


def _median(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _grp_stats(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "r3_pct": None,
            "r5_pct": None,
            "step_med": None,
            "sp_s3_med": None,
            "sp_s5_med": None,
            "s3_s5_med": None,
        }
    r3 = sum(r["reached3"] for r in rows)
    r5 = sum(r["reached5"] for r in rows)
    return {
        "n": n,
        "r3_pct": round(r3 / n * 100, 1),
        "r5_pct": round(r5 / n * 100, 1),
        "step_med": _median([r["step"] for r in rows]),
        "sp_s3_med": _median([r["sp_s3"] for r in rows]),
        "sp_s5_med": _median([r["sp_s5"] for r in rows]),
        "s3_s5_med": _median([r["s3_s5"] for r in rows]),
    }


def load_cohort(
    xlsx: Path,
    lstep_tsv: Path,
    *,
    year: int,
    month: int,
    snapshot: date,
    min_days_since_sp: int,
) -> list[dict]:
    df = pd.read_excel(xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, year, month, tokushin_only=True)
    idx = build_lstep_index(lstep_tsv)

    rows: list[dict] = []
    for s in students:
        hit = lookup_lstep(idx, s["name"]) or {}
        sp = hit.get("sp_start") or s.get("sp")
        if not sp:
            continue
        if norm_name(s["name"]) in SP50_EXCLUDE:
            continue
        if (snapshot - sp).days < min_days_since_sp:
            continue
        sa = s.get("self_analysis")
        sd = {n: d for n, d in hit.get("step_dates") or []}
        sa_received = sa is not None and sa <= snapshot
        sa_gap = (sa - sp).days if sa else None
        if sa_gap is not None and sa_gap <= 7:
            bucket = "sa7"
        elif sa_gap is not None and sa_gap <= 14:
            bucket = "sa814"
        elif sa_gap is not None:
            bucket = "sa15p"
        else:
            bucket = "none"
        rows.append(
            {
                "name": s["name"],
                "sa_received": sa_received,
                "bucket": bucket,
                "sa_gap": sa_gap,
                "step": hit.get("latest_step") or 0,
                "reached3": 3 in sd,
                "reached5": 5 in sd,
                "sp_s3": (sd[3] - sp).days if 3 in sd else None,
                "sp_s5": (sd[5] - sp).days if 5 in sd else None,
                "s3_s5": (sd[5] - sd[3]).days if 3 in sd and 5 in sd else None,
            }
        )
    return rows


def build_payload(rows: list[dict], snapshot: date) -> dict:
    return {
        "snapshot": snapshot.isoformat(),
        "total": len(rows),
        "sa_yes": _grp_stats([r for r in rows if r["sa_received"]]),
        "sa_no": _grp_stats([r for r in rows if not r["sa_received"]]),
        "sa7": _grp_stats([r for r in rows if r["bucket"] == "sa7"]),
        "sa814": _grp_stats([r for r in rows if r["bucket"] == "sa814"]),
        "sa15p": _grp_stats([r for r in rows if r["bucket"] == "sa15p"]),
        "students": rows,
    }


def render_html(data: dict, *, title: str, subtitle: str) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
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
  header p {{ margin: 0; font-size: 13px; color: #555; line-height: 1.6; }}
  main {{ padding: 20px 24px 40px; max-width: 1200px; margin: 0 auto; }}
  section {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }}
  h2 {{ margin: 0 0 8px; font-size: 16px; }}
  .note {{ font-size: 12px; color: #666; line-height: 1.6; margin: 0 0 14px; }}
  .alert {{ background: #fff8e1; border: 1px solid #f0c040; border-radius: 6px; padding: 10px 14px; font-size: 13px; margin-bottom: 16px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  @media (max-width: 800px) {{ .cards {{ grid-template-columns: 1fr 1fr; }} }}
  .card {{ background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; }}
  .card .label {{ font-size: 11px; color: #666; }}
  .card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ position: relative; height: 320px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: center; }}
  th {{ background: #eef2f7; }}
  td.name {{ text-align: left; white-space: nowrap; }}
  .g-sa7 {{ background: #e2efda; }}
  .g-sa814 {{ background: #fff2cc; }}
  .g-sa15p {{ background: #fce4d6; }}
  .g-none {{ background: #f2f2f2; }}
  .yes {{ color: #1e5631; font-weight: 600; }}
  .no {{ color: #833c0c; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<main>
  <section id="alert-box"></section>
  <section>
    <h2>サマリ</h2>
    <div class="cards" id="summary-cards"></div>
  </section>
  <section>
    <h2>① SA受講済 vs 未受講（母数比較）</h2>
    <p class="note">自己分析セッション実施日が集計基準日以前 = 受講済。コミットプラン自己分析列（W列）を参照。</p>
    <div class="charts">
      <div class="chart-box"><canvas id="chartSaDoneRate"></canvas></div>
      <div class="chart-box"><canvas id="chartSaDoneDays"></canvas></div>
    </div>
  </section>
  <section>
    <h2>② SAタイミング別（4月コホート内の実質比較）</h2>
    <p class="note">全員SA受講済のため、<strong>SP開始→自己分析までの日数（SA gap）</strong>で3群に分割。STEP3-5到達率の差が最も大きい。</p>
    <div class="charts">
      <div class="chart-box"><canvas id="chartTimingRate"></canvas></div>
      <div class="chart-box"><canvas id="chartTimingDays"></canvas></div>
    </div>
  </section>
  <section>
    <h2>生徒一覧</h2>
    <div style="overflow-x:auto"><table id="studentTable"><thead>
      <tr><th>生徒名</th><th>SA gap</th><th>グループ</th><th>STEP3</th><th>STEP5</th><th>現在STEP</th><th>SP→STEP5</th><th>STEP3→5</th></tr>
    </thead><tbody></tbody></table></div>
  </section>
</main>
<script>
const DATA = {payload};

function fmt(v, suffix='') {{
  if (v == null || v === '') return '—';
  return v + suffix;
}}

function renderAlert() {{
  const no = DATA.sa_no.n;
  const el = document.getElementById('alert-box');
  if (no === 0) {{
    el.innerHTML = '<div class="alert"><strong>注意:</strong> 4月入会・SP+30日コホート（' + DATA.total + '名）は<strong>全員自己分析セッション受講済</strong>（SA未受講 0名）です。'
      + '「受講済 vs 未受講」の母数比較はこのコホートではできないため、下段の<strong>SAタイミング別（7日以内 / 8-14日 / 15日超）</strong>を実質的な比較として参照してください。</div>';
  }} else {{
    el.innerHTML = '';
  }}
}}

function renderCards() {{
  const c = document.getElementById('summary-cards');
  const items = [
    ['母数', DATA.total + '名', ''],
    ['SA受講済', DATA.sa_yes.n + '名', ''],
    ['SA未受講', DATA.sa_no.n + '名', ''],
    ['SA 15日超', DATA.sa15p.n + '名', 'STEP5到達 ' + fmt(DATA.sa15p.r5_pct, '%')],
  ];
  c.innerHTML = items.map(([l,v,s]) => '<div class="card"><div class="label">' + l + '</div><div class="value">' + v + '</div>'
    + (s ? '<div class="label">' + s + '</div>' : '') + '</div>').join('');
}}

const chartDefaults = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ position: 'bottom' }} }},
}};

function barChart(id, labels, datasets, yLabel) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels, datasets }},
    options: {{
      ...chartDefaults,
      scales: {{ y: {{ beginAtZero: true, title: {{ display: !!yLabel, text: yLabel }} }} }},
    }},
  }});
}}

function renderCharts() {{
  barChart('chartSaDoneRate',
    ['STEP3到達率', 'STEP5到達率'],
    [
      {{ label: 'SA受講済 (n=' + DATA.sa_yes.n + ')', data: [DATA.sa_yes.r3_pct, DATA.sa_yes.r5_pct], backgroundColor: '#2e75b6' }},
      {{ label: 'SA未受講 (n=' + DATA.sa_no.n + ')', data: [DATA.sa_no.r3_pct ?? 0, DATA.sa_no.r5_pct ?? 0], backgroundColor: '#ccc' }},
    ],
    '%'
  );
  barChart('chartSaDoneDays',
    ['SP→STEP5', 'STEP3→STEP5', '現在STEP'],
    [
      {{ label: 'SA受講済', data: [DATA.sa_yes.sp_s5_med, DATA.sa_yes.s3_s5_med, DATA.sa_yes.step_med], backgroundColor: '#2e75b6' }},
      {{ label: 'SA未受講', data: [DATA.sa_no.sp_s5_med ?? 0, DATA.sa_no.s3_s5_med ?? 0, DATA.sa_no.step_med ?? 0], backgroundColor: '#ccc' }},
    ],
    '日数'
  );
  barChart('chartTimingRate',
    ['STEP3到達率', 'STEP5到達率'],
    [
      {{ label: 'SA 7日以内 (n=' + DATA.sa7.n + ')', data: [DATA.sa7.r3_pct, DATA.sa7.r5_pct], backgroundColor: '#548235' }},
      {{ label: 'SA 8-14日 (n=' + DATA.sa814.n + ')', data: [DATA.sa814.r3_pct, DATA.sa814.r5_pct], backgroundColor: '#bf8f00' }},
      {{ label: 'SA 15日超 (n=' + DATA.sa15p.n + ')', data: [DATA.sa15p.r3_pct, DATA.sa15p.r5_pct], backgroundColor: '#c55a11' }},
    ],
    '%'
  );
  barChart('chartTimingDays',
    ['SP→STEP5', 'STEP3→STEP5', '現在STEP'],
    [
      {{ label: 'SA 7日以内', data: [DATA.sa7.sp_s5_med, DATA.sa7.s3_s5_med, DATA.sa7.step_med], backgroundColor: '#548235' }},
      {{ label: 'SA 8-14日', data: [DATA.sa814.sp_s5_med, DATA.sa814.s3_s5_med, DATA.sa814.step_med], backgroundColor: '#bf8f00' }},
      {{ label: 'SA 15日超', data: [DATA.sa15p.sp_s5_med, DATA.sa15p.s3_s5_med, DATA.sa15p.step_med], backgroundColor: '#c55a11' }},
    ],
    '日数'
  );
}}

function bucketLabel(b) {{
  return {{ sa7: '7日以内', sa814: '8-14日', sa15p: '15日超', none: '未受講' }}[b] || b;
}}
function bucketClass(b) {{
  return {{ sa7: 'g-sa7', sa814: 'g-sa814', sa15p: 'g-sa15p', none: 'g-none' }}[b] || '';
}}

function renderTable() {{
  const tbody = document.querySelector('#studentTable tbody');
  const sorted = [...DATA.students].sort((a,b) => (a.sa_gap ?? 999) - (b.sa_gap ?? 999));
  tbody.innerHTML = sorted.map(r => '<tr class="' + bucketClass(r.bucket) + '"><td class="name">' + r.name + '</td>'
    + '<td>' + fmt(r.sa_gap, '日') + '</td><td>' + bucketLabel(r.bucket) + '</td>'
    + '<td class="' + (r.reached3 ? 'yes' : 'no') + '">' + (r.reached3 ? '○' : '×') + '</td>'
    + '<td class="' + (r.reached5 ? 'yes' : 'no') + '">' + (r.reached5 ? '○' : '×') + '</td>'
    + '<td>' + r.step + '</td><td>' + fmt(r.sp_s5, '日') + '</td><td>' + fmt(r.s3_s5, '日') + '</td></tr>').join('');
}}

renderAlert();
renderCards();
renderCharts();
renderTable();
</script>
</body>
</html>"""


def main() -> int:
    p = argparse.ArgumentParser(description="SA×STEP3-5 比較グラフHTML")
    p.add_argument("xlsx", type=Path, nargs="?", default=Path.home() / "Downloads/コミットプラン (9).xlsx")
    p.add_argument("--lstep", type=Path, default=ROOT / "data/metadata/lstep_tokushin_userpaste.tsv")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=4)
    p.add_argument("--snapshot", default="2026-06-04")
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument("-o", type=Path, default=ROOT / "data/reports/monthly_20260604/sa_step35_compare.html")
    args = p.parse_args()

    snapshot = date.fromisoformat(args.snapshot)
    rows = load_cohort(
        args.xlsx,
        args.lstep,
        year=args.year,
        month=args.month,
        snapshot=snapshot,
        min_days_since_sp=args.min_days,
    )
    data = build_payload(rows, snapshot)
    title = f"仮説A: STEP3-5 × 自己分析（{args.year}年{args.month}月入会・新特進）"
    subtitle = (
        f"集計基準日: {snapshot} ／ 母数: SP+{args.min_days}日経過 {len(rows)}名 ／ "
        f"SA受講済 {data['sa_yes']['n']}名 / SA未受講 {data['sa_no']['n']}名 ／ "
        f"データ: {args.xlsx.name} + {args.lstep.name}"
    )
    html = render_html(data, title=title, subtitle=subtitle)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(html, encoding="utf-8")
    print(f"Wrote {args.o} ({len(rows)} students, SA未={data['sa_no']['n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
