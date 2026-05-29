#!/usr/bin/env python3
"""
新特進コホートのセッション実施タイミングをスプレッドシート風ガントチャート（HTML）で出力する。
Lステップ（入会フォーム+3日=SP開始、STEP19=SP完了）とコミットプランを連携。

用法:
  python3 scripts/render_session_gantt.py
  python3 scripts/render_session_gantt.py "/path/to/コミットプラン (N).xlsx" --lstep "~/Downloads/Lステップ....xlsx"
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_commit_plan_cohort import load_students  # noqa: E402
from lstep_sp_lookup import build_lstep_index, lookup_lstep  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = Path.home() / "Downloads" / "コミットプラン (8).xlsx"
DEFAULT_LSTEP_TSV = ROOT / "data/metadata/lstep_tokushin.tsv"
DEFAULT_LSTEP_XLSX = Path.home() / "Downloads" / "Lステップの顧客データ (1).xlsx"
DEFAULT_OUT = ROOT / "data/reports/session_timeline_202604.html"


def resolve_lstep_path(explicit: Path | None) -> Path | None:
    """貼付更新用TSV → xlsx の順で解決。"""
    if explicit and explicit.exists():
        return explicit
    if DEFAULT_LSTEP_TSV.exists():
        return DEFAULT_LSTEP_TSV
    if DEFAULT_LSTEP_XLSX.exists():
        return DEFAULT_LSTEP_XLSX
    return explicit


def resolve_sp(student: dict, lstep_index: dict | None) -> tuple[date | None, str]:
    """Returns (sp_date, source_label)."""
    if lstep_index:
        hit = lookup_lstep(lstep_index, student["name"])
        if hit:
            student["lstep"] = hit
            return hit["sp_start"], "Lステップ"
    if student.get("sp"):
        return student["sp"], "コミットプラン"
    return None, ""


def day_label(d: int) -> str:
    return "SP開始" if d == 0 else f"{d}日目"


def build_timeline_rows(students: list[dict], lstep_index: dict | None) -> list[dict]:
    rows = []
    for s in students:
        sp, sp_src = resolve_sp(s, lstep_index)
        if not sp:
            continue

        lstep = s.get("lstep") or {}
        events: list[dict] = []

        # SP各STEP（Lステップ）
        for step_n, step_d in lstep.get("step_dates") or []:
            day = (step_d - sp).days
            events.append({"day": day, "kind": "step", "label": f"STEP{step_n}"})

        sp_complete = lstep.get("sp_complete")
        if sp_complete:
            day = (sp_complete - sp).days
            events.append(
                {
                    "day": day,
                    "kind": "sp_done",
                    "label": f"SP完了(STEP{lstep.get('latest_step', 19)})",
                }
            )

        if s.get("self_analysis"):
            day = (s["self_analysis"] - sp).days
            events.append({"day": day, "kind": "sa", "label": "自己分析"})

        for i, cd in enumerate(s.get("coaching_dates") or []):
            day = (cd - sp).days
            events.append({"day": day, "kind": "coach", "label": f"ｾｯｼｮﾝ{i}"})

        sp_complete_day = (sp_complete - sp).days if sp_complete else None

        rows.append(
            {
                "name": s["name"],
                "mg": s.get("mg") or "",
                "sp": sp,
                "sp_src": sp_src,
                "sp_complete_day": sp_complete_day,
                "latest_step": lstep.get("latest_step", 0),
                "events": events,
                "sa_gap": (s["self_analysis"] - sp).days if s.get("self_analysis") else None,
            }
        )
    rows.sort(key=lambda r: (r["mg"], r["name"]))
    return rows


def pill_html(e: dict) -> str:
    labels = {
        "step": lambda: str(e["label"].replace("STEP", "")),
        "sp_done": lambda: "SP完了",
        "sa": lambda: "自己分析",
        "coach": lambda: "ｾｯｼｮﾝ",
    }
    text = labels.get(e["kind"], lambda: e["label"])()
    return f'<span class="pill {e["kind"]}" title="{html.escape(e["label"])}">{html.escape(text)}</span>'


def render_panel_html(rows: list[dict], max_day: int, name_w: int, mg_w: int, cell_w: int) -> str:
    def header_cells() -> str:
        return "".join(
            f'<div class="day-head{" sp-col" if d == 0 else ""}" style="width:{cell_w}px">{html.escape(day_label(d))}</div>'
            for d in range(max_day + 1)
        )

    def row_cells(r: dict) -> str:
        by_day: dict[int, list[dict]] = {}
        for e in r["events"]:
            if 0 <= e["day"] <= max_day:
                by_day.setdefault(e["day"], []).append(e)
        sp_end = r.get("sp_complete_day")
        parts = []
        for d in range(max_day + 1):
            evs = by_day.get(d, [])
            inner = "".join(pill_html(e) for e in evs)
            cls = "day-cell"
            if d == 0:
                cls += " sp-col"
            if sp_end is not None and 0 < d <= sp_end:
                cls += " sp-range"
            parts.append(f'<div class="{cls}" style="width:{cell_w}px">{inner}</div>')
        return "".join(parts)

    head = f"""
    <div class="chart-wrap">
      <div class="head-row">
        <div class="name-cell" style="width:{name_w}px">生徒名</div>
        <div class="mg-cell" style="width:{mg_w}px">MG</div>
        <div class="track">{header_cells()}</div>
      </div>
    """
    body = ""
    for r in rows:
        meta = ""
        if r.get("latest_step"):
            meta = f' <span class="meta">STEP{r["latest_step"]}</span>'
        elif r.get("sp_src") == "Lステップ":
            meta = ' <span class="meta">SP未着手</span>'
        body += f"""
      <div class="student-row">
        <div class="name-cell" style="width:{name_w}px">{html.escape(r['name'])}{meta}</div>
        <div class="mg-cell" style="width:{mg_w}px">{html.escape(r['mg'])}</div>
        <div class="track">{row_cells(r)}</div>
      </div>"""
    return head + body + "</div>"


def build_full_html(rows: list[dict], title: str, source: str, lstep_source: str) -> str:
    name_w, mg_w, cell_w = 200, 88, 32
    sp_max = max((r["sp_complete_day"] or 0 for r in rows), default=30)
    sp_max = max(sp_max + 3, 30)
    p1 = render_panel_html(rows, 30, name_w, mg_w, cell_w)
    p2 = render_panel_html(rows, sp_max, name_w, mg_w, cell_w)
    p3 = render_panel_html(rows, 60, name_w, mg_w, cell_w)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif; margin: 0; background: #f5f5f5; }}
  header {{ padding: 16px 20px; background: #fff; border-bottom: 1px solid #ddd; }}
  header h1 {{ margin: 0 0 6px; font-size: 18px; }}
  header p {{ margin: 0; font-size: 13px; color: #555; }}
  .legend {{ display: flex; gap: 14px; margin-top: 10px; font-size: 12px; flex-wrap: wrap; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 5px; }}
  .swatch {{ width: 14px; height: 14px; border-radius: 2px; display: inline-block; }}
  .swatch.step {{ background: #548235; }}
  .swatch.sp_done {{ background: #7030a0; }}
  .swatch.sa {{ background: #2e75b6; }}
  .swatch.coach {{ background: #ed7d31; }}
  .swatch.range {{ background: #bdd7ee; border: 1px solid #9dc3e6; }}
  .tabs {{ padding: 12px 20px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
  .tab {{ padding: 8px 14px; border: 1px solid #ccc; background: #fff; cursor: pointer; border-radius: 6px 6px 0 0; font-size: 13px; }}
  .tab.active {{ background: #e2efda; border-bottom-color: #e2efda; font-weight: 600; }}
  .panel {{ display: none; padding: 0 12px 24px; overflow-x: auto; }}
  .panel.active {{ display: block; }}
  .chart-wrap {{ background: #fff; border: 1px solid #999; display: inline-block; min-width: 100%; }}
  .head-row, .student-row {{ display: flex; border-bottom: 1px solid #999; }}
  .head-row {{ background: #fff; font-size: 10px; font-weight: 600; }}
  .name-cell, .mg-cell, .day-head, .day-cell {{
    flex-shrink: 0; border-right: 1px solid #bbb; padding: 3px 4px;
  }}
  .name-cell {{ font-size: 12px; background: #f9f9f9; position: sticky; left: 0; z-index: 2; }}
  .mg-cell {{ font-size: 11px; background: #f9f9f9; position: sticky; left: {name_w}px; z-index: 2; }}
  .track {{ display: flex; }}
  .day-head, .day-cell {{ width: {cell_w}px; min-height: 34px; text-align: center; font-size: 9px;
    display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 1px; }}
  .student-row .day-cell {{ background: #c6e0b4; }}
  .day-cell.sp-range {{ background: #d9e8f7; }}
  .sp-col {{ background: #ffe699 !important; }}
  .pill {{ font-size: 8px; padding: 1px 2px; border-radius: 2px; color: #fff; font-weight: 700; line-height: 1.15; }}
  .pill.step {{ background: #548235; min-width: 12px; }}
  .pill.sp_done {{ background: #7030a0; font-size: 7px; }}
  .pill.sa {{ background: #2e75b6; }}
  .pill.coach {{ background: #ed7d31; border: 1px solid #bf6920; }}
  .meta {{ font-size: 9px; color: #666; font-weight: normal; }}
  .note {{ padding: 8px 20px; font-size: 12px; color: #666; line-height: 1.6; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>コミットプラン: {html.escape(source)} ／ Lステップ: {html.escape(lstep_source)} ／ {len(rows)}名</p>
  <div class="legend">
    <span><span class="swatch range"></span> SPプログラム期間（STEP1〜完了）</span>
    <span><span class="swatch step"></span> STEP完了（数字）</span>
    <span><span class="swatch sp_done"></span> SPプログラム完了</span>
    <span><span class="swatch sa"></span> 自己分析</span>
    <span><span class="swatch coach"></span> コーチング</span>
  </div>
</header>
<div class="tabs">
  <button class="tab active" onclick="show('p1', this)">SP〜30日（序盤）</button>
  <button class="tab" onclick="show('p2', this)">SPプログラム期間（〜{sp_max}日）</button>
  <button class="tab" onclick="show('p3', this)">SP〜60日（コーチング）</button>
</div>
<div id="p1" class="panel active">{p1}</div>
<div id="p2" class="panel">{p2}</div>
<div id="p3" class="panel">{p3}</div>
<p class="note">
  SP開始日 = Lステップ「入会フォーム回答日」+ 3日。<br>
  Lステップを更新したら <code>python3 scripts/render_session_gantt.py --lstep "最新.xlsx"</code> で再生成。<br>
  TSV貼付運用: <code>python3 scripts/export_lstep_tsv.py</code> → <code>data/metadata/lstep_tokushin.tsv</code> を編集可。
</p>
<script>
function show(id, btn) {{
  document.querySelectorAll('.panel,.tab').forEach(e => e.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx", nargs="?", type=Path, default=DEFAULT_XLSX)
    parser.add_argument(
        "--lstep",
        type=Path,
        default=None,
        help="Lステップ xlsx/tsv（省略時: data/metadata/lstep_tokushin.tsv → Downloads xlsx）",
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=4)
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.xlsx.exists():
        print(f"Not found: {args.xlsx}", file=sys.stderr)
        return 1

    lstep_path = resolve_lstep_path(args.lstep)
    lstep_index = None
    lstep_label = "(なし)"
    if lstep_path and lstep_path.exists():
        lstep_index = build_lstep_index(lstep_path)
        lstep_label = str(lstep_path.relative_to(ROOT)) if lstep_path.is_relative_to(ROOT) else lstep_path.name
        print(f"Lステップ: {len(lstep_index)}名読込 ({lstep_label})")
    else:
        print("Warning: Lステップ not found", file=sys.stderr)

    df = pd.read_excel(args.xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, args.year, args.month, tokushin_only=True)
    rows = build_timeline_rows(students, lstep_index)
    if not rows:
        print("No rows with SP date", file=sys.stderr)
        return 1

    matched = sum(1 for r in rows if r["sp_src"] == "Lステップ")
    title = f"セッション実施タイムライン（{args.year}年{args.month}月入会・新特進）"
    html_out = build_full_html(rows, title, args.xlsx.name, lstep_label)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding="utf-8")
    print(f"Wrote {args.output} ({len(rows)} students, Lステップ連携 {matched}名)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
