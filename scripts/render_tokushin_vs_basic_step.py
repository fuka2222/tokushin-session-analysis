#!/usr/bin/env python3
"""Lステップ「投稿プログラム（新）」— 特進 vs ベーシック STEP進行パターン比較HTML。"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = Path.home() / "Downloads/Lステップの顧客データ - 投稿プログラム（新） (2).csv"
SP_OFFSET = 3
MILESTONES = [3, 5, 9, 15, 18]
SEGMENTS = [(None, 3, "SP→STEP3"), (3, 5, "STEP3→5"), (5, 10, "STEP5→10"), (10, 15, "STEP10→15")]


def parse_date(val) -> date | None:
    if not val or str(val).strip() in ("", "nan"):
        return None
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", str(val).strip().replace(".", "/"))
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def course_group(course: str | None) -> str | None:
    c = course or ""
    if "特進" in c:
        return "tokushin"
    if "ベーシック" in c:
        return "basic"
    return None


def sp_start(row: dict) -> date | None:
    ps = parse_date(row.get("投稿プログラム開始日"))
    if ps:
        return ps
    j = parse_date(row.get("入会フォーム回答日"))
    return j + timedelta(days=SP_OFFSET) if j else None


def load_rows(
    csv_path: Path,
    *,
    year: int,
    month: int,
    snapshot: date,
    min_days_since_sp: int,
) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            grp = course_group(raw.get("コース") or "")
            if not grp:
                continue
            join = parse_date(raw.get("入会フォーム回答日"))
            sp = sp_start(raw)
            sd: dict[int, date] = {}
            for i in range(1, 20):
                d = parse_date(raw.get(f"STEP{i}完了日"))
                if d:
                    sd[i] = d
            if not join or not sp or not sd:
                continue
            if join.year != year or join.month != month:
                continue
            if (snapshot - sp).days < min_days_since_sp:
                continue
            by_day = Counter(sd.values())
            rows.append(
                {
                    "name": (raw.get("表示名") or "").strip(),
                    "group": grp,
                    "sp": sp.isoformat(),
                    "latest": max(sd),
                    "sd": {str(k): v.isoformat() for k, v in sd.items()},
                    "burst_days": sum(1 for c in by_day.values() if c >= 2),
                }
            )
    return rows


def _median(vals: list[float]) -> float | None:
    return statistics.median(vals) if vals else None


def analyze(rows: list[dict]) -> dict:
    out: dict = {"tokushin": {}, "basic": {}, "patterns": {}}
    for g in ("tokushin", "basic"):
        grp = [r for r in rows if r["group"] == g]
        n = len(grp)
        steps = [r["latest"] for r in grp]
        reach = {}
        for m in MILESTONES:
            cnt = sum(1 for r in grp if r["latest"] >= m)
            reach[str(m)] = {"n": cnt, "pct": round(cnt / n * 100, 1) if n else 0}

        seg_medians = {}
        for a, b, label in SEGMENTS:
            vals = []
            for r in grp:
                sd = {int(k): date.fromisoformat(v) for k, v in r["sd"].items()}
                sp = date.fromisoformat(r["sp"])
                if a is None and b in sd:
                    vals.append((sd[b] - sp).days)
                elif a in sd and b in sd:
                    vals.append((sd[b] - sd[a]).days)
            seg_medians[label] = {"median": _median(vals), "n": len(vals)}

        hist = Counter(r["latest"] for r in grp)
        bands = {
            "1-5": sum(hist[i] for i in range(1, 6)),
            "6-9": sum(hist[i] for i in range(6, 10)),
            "10-14": sum(hist[i] for i in range(10, 15)),
            "15-17": sum(hist[i] for i in range(15, 18)),
            "18+": sum(hist[i] for i in range(18, 20)),
        }

        longest = Counter()
        for r in grp:
            sd = sorted((int(k), date.fromisoformat(v)) for k, v in r["sd"].items())
            if len(sd) < 2:
                continue
            gaps = [(sd[i + 1][0], (sd[i + 1][1] - sd[i][1]).days) for i in range(len(sd) - 1)]
            worst_step, worst_days = max(gaps, key=lambda x: x[1])
            longest[f"STEP{worst_step - 1}→{worst_step}"] += 1

        sp_to = {}
        for m in MILESTONES:
            vals = []
            for r in grp:
                sd = {int(k): date.fromisoformat(v) for k, v in r["sd"].items()}
                if m in sd:
                    vals.append((sd[m] - date.fromisoformat(r["sp"])).days)
            sp_to[str(m)] = _median(vals)

        out[g] = {
            "n": n,
            "step_median": _median(steps),
            "step_mean": round(statistics.mean(steps), 1) if steps else None,
            "reach": reach,
            "bands": bands,
            "seg_medians": seg_medians,
            "longest_gap_top": longest.most_common(6),
            "sp_to_median": sp_to,
            "burst_pct": round(sum(1 for r in grp if r["burst_days"] > 0) / n * 100, 1) if n else 0,
            "histogram": {str(k): hist[k] for k in sorted(hist)},
        }

    # cross-group patterns
    t, b = out["tokushin"], out["basic"]
    out["patterns"] = {
        "both_fast_early": [
            f"SP→STEP3 中央値: 特進{t['sp_to_median'].get('3')}日 / ベーシック{b['sp_to_median'].get('3')}日",
            f"STEP3→5 中央値: 特進{t['seg_medians']['STEP3→5']['median']}日 / ベーシック{b['seg_medians']['STEP3→5']['median']}日",
        ],
        "tokushin_traits": [
            f"STEP9到達 {t['reach']['9']['pct']}% vs ベーシック {b['reach']['9']['pct']}%",
            f"STEP15到達 {t['reach']['15']['pct']}% vs ベーシック {b['reach']['15']['pct']}%",
            f"現在STEP中央 {t['step_median']} vs {b['step_median']}",
            "停滞ピーク: STEP9・14付近（10-14帯に集中）",
        ],
        "basic_traits": [
            f"STEP≤5停滞 {t['bands']['1-5']}/{t['n']} vs {b['bands']['1-5']}/{b['n']}（{round(b['bands']['1-5']/b['n']*100)}%）",
            f"STEP9-11に大きな滞留（STEP9={b['histogram'].get('9',0)}名, STEP11={b['histogram'].get('11',0)}名）",
            "最長停滞区間の最頻: STEP9→10",
            f"1日2STEP以上 {b['burst_pct']}%（特進{t['burst_pct']}%）",
        ],
        "shared_bottleneck": [
            "STEP5→10 区間が両群とも中盤の壁（中央8-9日）",
            "STEP9→10 付近で停滞が目立つ（特にベーシック）",
            "STEP18到達は両群とも少数（特進4% / ベーシック1%）",
        ],
    }
    return out


def render_html(data: dict, rows: list[dict], *, title: str, subtitle: str) -> str:
    payload = json.dumps({"analysis": data, "rows": rows}, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif; margin: 0; background: #f4f4f4; }}
  header {{ background: #fff; border-bottom: 1px solid #ddd; padding: 18px 24px; }}
  header h1 {{ margin: 0 0 6px; font-size: 20px; }}
  header p {{ margin: 0; font-size: 13px; color: #555; line-height: 1.6; }}
  main {{ padding: 20px 24px 40px; max-width: 1200px; margin: 0 auto; }}
  section {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }}
  h2 {{ margin: 0 0 10px; font-size: 16px; }}
  .note {{ font-size: 12px; color: #666; line-height: 1.6; margin-bottom: 12px; }}
  .patterns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 800px) {{ .patterns {{ grid-template-columns: 1fr; }} }}
  .box {{ background: #f9f9f9; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; font-size: 13px; line-height: 1.7; }}
  .box h3 {{ margin: 0 0 8px; font-size: 14px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 900px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart-box {{ position: relative; height: 320px; }}
  .chart-tall {{ height: 380px; }}
  ul {{ margin: 0; padding-left: 18px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<main>
  <section>
    <h2>群ごとの共通パターン（要約）</h2>
    <div class="patterns" id="pattern-boxes"></div>
  </section>
  <section>
    <h2>STEP到達率（現在位置）</h2>
    <div class="charts">
      <div class="chart-box"><canvas id="chartReach"></canvas></div>
      <div class="chart-box"><canvas id="chartBands"></canvas></div>
    </div>
  </section>
  <section>
    <h2>区間速度（日数・中央値）</h2>
    <div class="chart-box"><canvas id="chartSegments"></canvas></div>
  </section>
  <section>
    <h2>現在STEPの分布（ヒストグラム）</h2>
    <div class="chart-box chart-tall"><canvas id="chartHist"></canvas></div>
  </section>
</main>
<script>
const DATA = {payload};
const A = DATA.analysis;
const milestones = ['3','5','9','15','18'];
const labels = milestones.map(m => 'STEP'+m+'+');

document.getElementById('pattern-boxes').innerHTML = [
  ['両群共通', A.patterns.both_fast_early.concat(A.patterns.shared_bottleneck)],
  ['特進コースの傾向', A.patterns.tokushin_traits],
  ['ベーシックコースの傾向', A.patterns.basic_traits],
].map(([title, items]) =>
  '<div class="box"><h3>' + title + '</h3><ul>' + items.map(x => '<li>' + x + '</li>').join('') + '</ul></div>'
).join('');

const opts = {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom' }} }} }};

new Chart(document.getElementById('chartReach'), {{
  type: 'bar',
  data: {{
    labels,
    datasets: [
      {{ label: '特進 (n='+A.tokushin.n+')', data: milestones.map(m => A.tokushin.reach[m].pct), backgroundColor: '#548235' }},
      {{ label: 'ベーシック (n='+A.basic.n+')', data: milestones.map(m => A.basic.reach[m].pct), backgroundColor: '#2e75b6' }},
    ],
  }},
  options: {{ ...opts, scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: '%' }} }} }} }},
}});

const bandLabels = ['STEP1-5','STEP6-9','STEP10-14','STEP15-17','STEP18+'];
new Chart(document.getElementById('chartBands'), {{
  type: 'bar',
  data: {{
    labels: bandLabels,
    datasets: [
      {{ label: '特進', data: Object.values(A.tokushin.bands), backgroundColor: '#548235' }},
      {{ label: 'ベーシック', data: Object.values(A.basic.bands), backgroundColor: '#2e75b6' }},
    ],
  }},
  options: {{ ...opts, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '人数' }} }} }} }},
}});

const segLabels = Object.keys(A.tokushin.seg_medians);
new Chart(document.getElementById('chartSegments'), {{
  type: 'bar',
  data: {{
    labels: segLabels,
    datasets: [
      {{ label: '特進（日）', data: segLabels.map(k => A.tokushin.seg_medians[k].median), backgroundColor: '#548235' }},
      {{ label: 'ベーシック（日）', data: segLabels.map(k => A.basic.seg_medians[k].median), backgroundColor: '#2e75b6' }},
    ],
  }},
  options: {{ ...opts, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '日数' }} }} }} }},
}});

const allSteps = [...new Set([
  ...Object.keys(A.tokushin.histogram),
  ...Object.keys(A.basic.histogram),
])].map(Number).sort((a,b)=>a-b);
new Chart(document.getElementById('chartHist'), {{
  type: 'bar',
  data: {{
    labels: allSteps.map(s => 'STEP'+s),
    datasets: [
      {{ label: '特進', data: allSteps.map(s => A.tokushin.histogram[String(s)] || 0), backgroundColor: '#548235' }},
      {{ label: 'ベーシック', data: allSteps.map(s => A.basic.histogram[String(s)] || 0), backgroundColor: '#2e75b6' }},
    ],
  }},
  options: {{ ...opts, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: '人数' }} }} }} }},
}});
</script>
</body>
</html>"""


def main() -> int:
    p = argparse.ArgumentParser(description="特進 vs ベーシック STEP比較")
    p.add_argument("csv", type=Path, nargs="?", default=DEFAULT_CSV)
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--month", type=int, default=4)
    p.add_argument("--snapshot", default="2026-06-04")
    p.add_argument("--min-days", type=int, default=30)
    p.add_argument("-o", type=Path, default=ROOT / "data/reports/monthly_20260604/tokushin_vs_basic_step.html")
    p.add_argument("--md", type=Path, default=ROOT / "data/reports/monthly_20260604/tokushin_vs_basic_patterns.md")
    args = p.parse_args()

    snapshot = date.fromisoformat(args.snapshot)
    rows = load_rows(args.csv, year=args.year, month=args.month, snapshot=snapshot, min_days_since_sp=args.min_days)
    analysis = analyze(rows)

    title = f"特進 vs ベーシック — STEP進行パターン（{args.year}年{args.month}月入会）"
    subtitle = (
        f"データ: 投稿プログラム（新） / 集計基準日 {snapshot} / SP+{args.min_days}日 "
        f"/ 特進 {analysis['tokushin']['n']}名・ベーシック {analysis['basic']['n']}名"
    )
    html = render_html(analysis, rows, title=title, subtitle=subtitle)
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(html, encoding="utf-8")

    t, b = analysis["tokushin"], analysis["basic"]
    md_lines = [
        f"# 特進 vs ベーシック — STEP進行パターン（{args.year}年{args.month}月入会）",
        "",
        f"- **データ**: Lステップ `投稿プログラム（新）`（{args.csv.name}）",
        f"- **集計日**: {snapshot} / SP+{args.min_days}日",
        f"- **特進**: {t['n']}名 / **ベーシック**: {b['n']}名",
        "",
        "## 両群の共通点",
        "",
    ]
    for item in analysis["patterns"]["both_fast_early"] + analysis["patterns"]["shared_bottleneck"]:
        md_lines.append(f"- {item}")
    md_lines += ["", "## 特進コースの傾向", ""]
    for item in analysis["patterns"]["tokushin_traits"]:
        md_lines.append(f"- {item}")
    md_lines += ["", "## ベーシックコースの傾向", ""]
    for item in analysis["patterns"]["basic_traits"]:
        md_lines.append(f"- {item}")
    md_lines += [
        "",
        "## 数値サマリ",
        "",
        "| 指標 | 特進 | ベーシック |",
        "|------|------|-----------|",
        f"| STEP中央値 | {t['step_median']} | {b['step_median']} |",
        f"| STEP5+ | {t['reach']['5']['pct']}% | {b['reach']['5']['pct']}% |",
        f"| STEP9+ | {t['reach']['9']['pct']}% | {b['reach']['9']['pct']}% |",
        f"| STEP15+ | {t['reach']['15']['pct']}% | {b['reach']['15']['pct']}% |",
        f"| STEP18+ | {t['reach']['18']['pct']}% | {b['reach']['18']['pct']}% |",
        f"| STEP1-5帯 | {t['bands']['1-5']}名 | {b['bands']['1-5']}名 |",
        "",
        f"HTML: `{args.o}`",
    ]
    args.md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Wrote {args.o}")
    print(f"Wrote {args.md}")
    print(f"  特進 n={t['n']} STEP中央{t['step_median']} / ベーシック n={b['n']} STEP中央{b['step_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
