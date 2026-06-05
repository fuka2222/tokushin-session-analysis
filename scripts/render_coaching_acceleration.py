#!/usr/bin/env python3
"""伴走セッション前後のSTEP進行加速指標を集計し、HTMLグラフを出力する。"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import date, timedelta
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


def _steps_in_window(step_dates: list[tuple[int, date]], start: date, end: date) -> int:
    return sum(1 for _, d in step_dates if start <= d <= end)


def _max_steps_one_day(step_dates: list[tuple[int, date]], start: date, end: date) -> int:
    by_day = Counter(d for _, d in step_dates if start <= d <= end)
    return max(by_day.values()) if by_day else 0


def _interstep_cv(steps: list[tuple[int, date]]) -> float | None:
    if len(steps) < 3:
        return None
    ds = sorted(d for _, d in steps)
    gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
    mean = statistics.mean(gaps)
    if mean == 0:
        return 0.0
    return round(statistics.stdev(gaps) / mean, 2)


def analyze_cohort(
    xlsx: Path,
    lstep_tsv: Path,
    *,
    year: int,
    month: int,
    snapshot: date,
    min_days_since_sp: int,
) -> dict:
    df = pd.read_excel(xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, year, month, tokushin_only=True)
    idx = build_lstep_index(lstep_tsv)

    session_events: list[dict] = []
    student_rows: list[dict] = []
    skipped_no_steps = 0
    skipped_no_coach = 0

    for s in students:
        hit = lookup_lstep(idx, s["name"]) or {}
        sp = hit.get("sp_start") or s.get("sp")
        if not sp or norm_name(s["name"]) in SP50_EXCLUDE:
            continue
        if (snapshot - sp).days < min_days_since_sp:
            continue

        sd = sorted(hit.get("step_dates") or [], key=lambda x: x[0])
        coach = sorted(c for c in (s.get("coaching_dates") or []) if c <= snapshot)
        if len(sd) < 2:
            skipped_no_steps += 1
            continue
        if not coach:
            skipped_no_coach += 1
            continue

        by_day_all = Counter(d for _, d in sd)
        burst_days_total = sum(1 for c in by_day_all.values() if c >= 2)

        per_sess: list[dict] = []
        for i, c in enumerate(coach):
            before7 = _steps_in_window(sd, c - timedelta(days=7), c - timedelta(days=1))
            after7 = _steps_in_window(sd, c, c + timedelta(days=7))
            after3 = _steps_in_window(sd, c, c + timedelta(days=3))
            burst_after = _max_steps_one_day(sd, c, c + timedelta(days=7)) >= 2
            evt = {
                "name": s["name"],
                "session": i + 1,
                "coach_date": c.isoformat(),
                "before7": before7,
                "after7": after7,
                "after3": after3,
                "burst_after": burst_after,
                "delta7": after7 - before7,
            }
            per_sess.append(evt)
            session_events.append(evt)

        c1 = coach[0]
        before_all = [(n, d) for n, d in sd if d < c1]
        after_all = [(n, d) for n, d in sd if d >= c1]
        by_before = Counter(d for _, d in before_all)
        by_after = Counter(d for _, d in after_all)

        student_rows.append(
            {
                "name": s["name"],
                "n_coach": len(coach),
                "n_steps": len(sd),
                "burst_days_total": burst_days_total,
                "max_steps_per_day": max(by_day_all.values()),
                "steps_after_c1_7d": _steps_in_window(sd, c1, c1 + timedelta(days=7)),
                "sess_after7_ge2": sum(1 for p in per_sess if p["after7"] >= 2),
                "sess_burst_after": sum(1 for p in per_sess if p["burst_after"]),
                "avg_before7": round(statistics.mean([p["before7"] for p in per_sess]), 1),
                "avg_after7": round(statistics.mean([p["after7"] for p in per_sess]), 1),
                "cv_before": _interstep_cv(before_all),
                "cv_after": _interstep_cv(after_all),
                "burst_before": sum(1 for c in by_before.values() if c >= 2),
                "burst_after": sum(1 for c in by_after.values() if c >= 2),
            }
        )

    n_sess = len(session_events)
    n_st = len(student_rows)

    def pct(num: int, den: int) -> float | None:
        return round(num / den * 100, 1) if den else None

    summary = {
        "students": n_st,
        "sessions": n_sess,
        "skipped_no_steps": skipped_no_steps,
        "skipped_no_coach": skipped_no_coach,
        "sess_after7_ge2_pct": pct(sum(1 for e in session_events if e["after7"] >= 2), n_sess),
        "sess_after7_ge1_pct": pct(sum(1 for e in session_events if e["after7"] >= 1), n_sess),
        "sess_burst_after_pct": pct(sum(1 for e in session_events if e["burst_after"]), n_sess),
        "sess_delta7_up_pct": pct(sum(1 for e in session_events if e["delta7"] > 0), n_sess),
        "median_before7": statistics.median([e["before7"] for e in session_events]) if session_events else None,
        "median_after7": statistics.median([e["after7"] for e in session_events]) if session_events else None,
        "students_c1_7d_ge2_pct": pct(sum(1 for s in student_rows if s["steps_after_c1_7d"] >= 2), n_st),
        "students_any_burst_after_pct": pct(
            sum(1 for s in student_rows if s["sess_burst_after"] > 0), n_st
        ),
        "students_more_regular_pct": pct(
            sum(
                1
                for s in student_rows
                if s["cv_before"] is not None
                and s["cv_after"] is not None
                and s["cv_after"] <= s["cv_before"]
            ),
            n_st,
        ),
        "students_burst_days_total_ge1_pct": pct(
            sum(1 for s in student_rows if s["burst_days_total"] >= 1), n_st
        ),
    }

    return {
        "summary": summary,
        "session_events": session_events,
        "students": sorted(student_rows, key=lambda x: -x["steps_after_c1_7d"]),
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
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  @media (max-width: 900px) {{ .cards {{ grid-template-columns: 1fr 1fr; }} }}
  .card {{ background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; }}
  .card .label {{ font-size: 11px; color: #666; }}
  .card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  .card .sub {{ font-size: 11px; color: #888; margin-top: 4px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ position: relative; height: 320px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: center; }}
  th {{ background: #eef2f7; }}
  td.name {{ text-align: left; white-space: nowrap; }}
  .hi {{ background: #e2efda; font-weight: 600; }}
  .mid {{ background: #fff2cc; }}
  .lo {{ background: #fce4d6; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<main>
  <section>
    <h2>サマリ — 伴走で進みが加速したか？</h2>
    <p class="note">
      Lステップ各STEP完了日 × コミットプラン伴走日（X列〜）を突合。
      「伴走後7日」= セッション当日〜7日後に完了したSTEP数。
      「1日2STEP以上」= 同一日に2つ以上のSTEP完了。
      STEP間隔のばらつき(CV)が伴走後に低下 = よりコンスタントに進んだ目安。
    </p>
    <div class="cards" id="summary-cards"></div>
  </section>
  <section>
    <h2>伴走セッション単位（1回ごと）の効果</h2>
    <div class="charts">
      <div class="chart-box"><canvas id="chartSessionRates"></canvas></div>
      <div class="chart-box"><canvas id="chartBeforeAfter7"></canvas></div>
    </div>
  </section>
  <section>
    <h2>初回伴走後7日以内のSTEP数（生徒別）</h2>
    <div class="chart-box" style="height:360px"><canvas id="chartC1_7d"></canvas></div>
  </section>
  <section>
    <h2>生徒別サマリ</h2>
    <div style="overflow-x:auto"><table id="studentTable"><thead>
      <tr>
        <th>生徒名</th><th>伴走回数</th><th>初回後7日STEP</th><th>7日2STEP+の回数</th>
        <th>1日2STEP日数</th><th>最大1日STEP</th><th>前7日→後7日(平均)</th>
        <th>CV 伴走前→後</th>
      </tr>
    </thead><tbody></tbody></table></div>
  </section>
</main>
<script>
const DATA = {payload};
const S = DATA.summary;

function renderCards() {{
  const items = [
    ['分析対象', S.students + '名 / ' + S.sessions + 'セッション', 'STEP2+ & 伴走1回以上'],
    ['伴走後7日でSTEP≥2', S.sess_after7_ge2_pct + '%', 'セッション単位'],
    ['伴走後7日で1日2STEP+', S.sess_burst_after_pct + '%', 'セッション単位'],
    ['前7日より後7日が多い', S.sess_delta7_up_pct + '%', 'セッション単位'],
    ['初回伴走後7日でSTEP≥2', S.students_c1_7d_ge2_pct + '%', '生徒単位'],
    ['1日2STEP以上経験', S.students_burst_days_total_ge1_pct + '%', '生徒単位'],
    ['伴走後CV↓(規則的)', S.students_more_regular_pct + '%', '生徒単位'],
    ['前7日/後7日 STEP中央', S.median_before7 + ' → ' + S.median_after7, 'セッション単位'],
  ];
  document.getElementById('summary-cards').innerHTML = items.map(([l,v,s]) =>
    '<div class="card"><div class="label">' + l + '</div><div class="value">' + v + '</div><div class="sub">' + s + '</div></div>'
  ).join('');
}}

const chartOpts = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ position: 'bottom' }} }},
}};

new Chart(document.getElementById('chartSessionRates'), {{
  type: 'bar',
  data: {{
    labels: ['伴走後7日\\nSTEP≥2', '伴走後7日\\nSTEP≥1', '伴走後7日\\n1日2STEP+', '後7日>前7日'],
    datasets: [{{
      label: '該当率 (%)',
      data: [S.sess_after7_ge2_pct, S.sess_after7_ge1_pct, S.sess_burst_after_pct, S.sess_delta7_up_pct],
      backgroundColor: ['#ed7d31', '#f4b183', '#c55a11', '#2e75b6'],
    }}],
  }},
  options: {{ ...chartOpts, scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: '%' }} }} }} }},
}});

new Chart(document.getElementById('chartBeforeAfter7'), {{
  type: 'bar',
  data: {{
    labels: ['伴走前7日', '伴走後7日'],
    datasets: [{{
      label: 'STEP数（セッション単位・中央値）',
      data: [S.median_before7, S.median_after7],
      backgroundColor: ['#bdd7ee', '#ed7d31'],
    }}],
  }},
  options: {{ ...chartOpts, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'STEP数' }} }} }} }},
}});

const topStudents = DATA.students.slice(0, 20);
new Chart(document.getElementById('chartC1_7d'), {{
  type: 'bar',
  data: {{
    labels: topStudents.map(s => s.name),
    datasets: [{{
      label: '初回伴走後7日以内のSTEP数',
      data: topStudents.map(s => s.steps_after_c1_7d),
      backgroundColor: topStudents.map(s => s.steps_after_c1_7d >= 2 ? '#548235' : '#d9d9d9'),
    }}],
  }},
  options: {{
    ...chartOpts,
    indexAxis: 'y',
    scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'STEP数' }} }} }},
  }},
}});

function rowClass(s) {{
  if (s.steps_after_c1_7d >= 4 || s.sess_after7_ge2 >= 2) return 'hi';
  if (s.steps_after_c1_7d >= 2) return 'mid';
  return 'lo';
}}

document.querySelector('#studentTable tbody').innerHTML = DATA.students.map(s =>
  '<tr class="' + rowClass(s) + '"><td class="name">' + s.name + '</td>'
  + '<td>' + s.n_coach + '</td><td>' + s.steps_after_c1_7d + '</td><td>' + s.sess_after7_ge2 + '</td>'
  + '<td>' + s.burst_days_total + '</td><td>' + s.max_steps_per_day + '</td>'
  + '<td>' + s.avg_before7 + ' → ' + s.avg_after7 + '</td>'
  + '<td>' + (s.cv_before ?? '—') + ' → ' + (s.cv_after ?? '—') + '</td></tr>'
).join('');

renderCards();
</script>
</body>
</html>"""


def main() -> int:
    p = argparse.ArgumentParser(description="伴走×STEP加速 グラフHTML")
    p.add_argument("xlsx", type=Path, nargs="?", default=Path.home() / "Downloads/コミットプラン (9).xlsx")
    p.add_argument("--lstep", type=Path, default=ROOT / "data/metadata/lstep_tokushin_userpaste.tsv")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=4)
    p.add_argument("--snapshot", default="2026-06-04")
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument("-o", type=Path, default=ROOT / "data/reports/monthly_20260604/coaching_acceleration.html")
    args = p.parse_args()

    snapshot = date.fromisoformat(args.snapshot)
    data = analyze_cohort(
        args.xlsx,
        args.lstep,
        year=args.year,
        month=args.month,
        snapshot=snapshot,
        min_days_since_sp=args.min_days,
    )
    s = data["summary"]
    title = f"伴走セッション × STEP加速（{args.year}年{args.month}月入会・新特進）"
    subtitle = (
        f"集計基準日: {snapshot} ／ 対象: STEP2+かつ伴走1回以上 {s['students']}名・{s['sessions']}セッション "
        f"（伴走なし{s['skipped_no_coach']}名・STEP不足{s['skipped_no_steps']}名は除外）"
    )
    html = render_html(data, title=title, subtitle=subtitle)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(html, encoding="utf-8")
    print(f"Wrote {args.o}")
    print(
        f"  伴走後7日STEP≥2: {s['sess_after7_ge2_pct']}% / "
        f"1日2STEP+: {s['sess_burst_after_pct']}% / "
        f"初回後7日STEP≥2: {s['students_c1_7d_ge2_pct']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
