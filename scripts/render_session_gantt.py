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
from analyze_commit_plan_cohort import load_students, normalize_mg  # noqa: E402
from lstep_sp_lookup import build_lstep_index, lookup_lstep, norm_name  # noqa: E402
from sp_start_lookup import load_sp_start_index, lookup_sp_start  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = Path.home() / "Downloads" / "コミットプラン (9).xlsx"
DEFAULT_LSTEP_TSV = ROOT / "data/metadata/lstep_tokushin_userpaste.tsv"
DEFAULT_LSTEP_TSV_FALLBACK = ROOT / "data/metadata/lstep_tokushin.tsv"
DEFAULT_LSTEP_XLSX = Path.home() / "Downloads" / "Lステップの顧客データ (1).xlsx"
DEFAULT_OUT = ROOT / "data/reports/session_timeline_202604.html"
SP_START_PATH = ROOT / "data/metadata/sp_start_dates.tsv"


def resolve_lstep_path(explicit: Path | None) -> Path | None:
    """貼付更新用TSV → 旧TSV → xlsx の順で解決。"""
    if explicit and explicit.exists():
        return explicit
    if DEFAULT_LSTEP_TSV.exists():
        return DEFAULT_LSTEP_TSV
    if DEFAULT_LSTEP_TSV_FALLBACK.exists():
        return DEFAULT_LSTEP_TSV_FALLBACK
    if DEFAULT_LSTEP_XLSX.exists():
        return DEFAULT_LSTEP_XLSX
    return explicit


def load_lstep_mg_short_names(path: Path) -> dict[str, str]:
    """Lステップ貼付TSVの「担当MG名」（短縮MG）を引く。"""
    import csv

    if not path.exists() or path.suffix.lower() not in (".tsv", ".csv"):
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if "担当MG名" not in (reader.fieldnames or []):
            return {}
        for raw in reader:
            name = (raw.get("表示名") or "").strip()
            mg = normalize_mg(raw.get("担当MG名"))
            if name and mg:
                out[norm_name(name)] = mg
    return out


def resolve_mg_display(student: dict, mg_short: dict[str, str]) -> str:
    """表示用MG: Lステップ短縮名 > コミットプラン担当MG名（日付除外）。"""
    key = norm_name(student["name"])
    if key in mg_short:
        return mg_short[key]
    for k, v in mg_short.items():
        if key in k or k in key:
            return v
    return normalize_mg(student.get("mg") or "")


def resolve_sp(student: dict, lstep_index: dict | None, sp_manual: dict | None = None) -> tuple[date | None, str]:
    """Returns (sp_date, source_label). 優先: sp_start_dates.tsv > Lステップ > コミットプラン列."""
    manual = lookup_sp_start(student["name"], sp_manual)
    if manual:
        return manual, "SP開始日マスタ"
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


def event_status(event_date: date, as_of: date) -> str:
    """as_of 以前 = 実施済み、以降 = 予定。"""
    return "done" if event_date <= as_of else "scheduled"


def build_timeline_rows(
    students: list[dict],
    lstep_index: dict | None,
    sp_manual: dict | None = None,
    mg_short: dict[str, str] | None = None,
    as_of: date | None = None,
) -> list[dict]:
    mg_short = mg_short or {}
    as_of = as_of or date.today()
    rows = []
    for s in students:
        sp, sp_src = resolve_sp(s, lstep_index, sp_manual)
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
            if day >= 0:
                step_n = lstep.get("latest_step", 19)
                events.append(
                    {
                        "day": day,
                        "kind": "sp_done",
                        "label": f"SP完了(STEP{step_n})",
                    }
                )

        if s.get("self_analysis"):
            sa_d = s["self_analysis"]
            day = (sa_d - sp).days
            events.append(
                {
                    "day": day,
                    "kind": "sa",
                    "label": "自己分析",
                    "event_date": sa_d,
                    "status": event_status(sa_d, as_of),
                }
            )

        for i, cd in enumerate(s.get("coaching_dates") or []):
            day = (cd - sp).days
            events.append(
                {
                    "day": day,
                    "kind": "coach",
                    "label": f"伴走{i + 1}",
                    "event_date": cd,
                    "status": event_status(cd, as_of),
                }
            )

        sp_complete_day = (sp_complete - sp).days if sp_complete else None
        mg_display = resolve_mg_display(s, mg_short)

        rows.append(
            {
                "name": s["name"],
                "mg": mg_display,
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
        "coach": lambda: "伴走",
    }
    text = labels.get(e["kind"], lambda: e["label"])()
    status = e.get("status")
    status_cls = f" {status}" if status in ("done", "scheduled") else ""
    title = e["label"]
    if e.get("event_date"):
        tag = "実施済" if status == "done" else "予定"
        title = f"{e['label']} ({e['event_date'].isoformat()}・{tag})"
    return (
        f'<span class="pill {e["kind"]}{status_cls}" title="{html.escape(title)}">'
        f"{html.escape(text)}</span>"
    )


def _session_cell_class(evs: list[dict]) -> str:
    """自己分析・伴走セルの背景（予定が1つでもあれば future）。"""
    sessions = [e for e in evs if e.get("kind") in ("sa", "coach")]
    if not sessions:
        return ""
    if any(e.get("status") == "scheduled" for e in sessions):
        return " session-future"
    return " session-done"


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
            cls += _session_cell_class(evs)
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


def build_full_html(
    rows: list[dict], title: str, source: str, lstep_source: str, as_of: date
) -> str:
    name_w, mg_w, cell_w = 180, 72, 32
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
  .swatch.sa.scheduled {{ background: #fff; border: 2px dashed #2e75b6; }}
  .swatch.coach {{ background: #ed7d31; }}
  .swatch.coach.scheduled {{ background: #fff; border: 2px dashed #ed7d31; }}
  .swatch.range {{ background: #bdd7ee; border: 1px solid #9dc3e6; }}
  .swatch.future-cell {{ background: #fef9e7; border: 1px dashed #e8c547; }}
  .tabs {{ padding: 12px 20px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
  .tab {{ padding: 8px 14px; border: 1px solid #ccc; background: #fff; cursor: pointer; border-radius: 6px 6px 0 0; font-size: 13px; }}
  .tab.active {{ background: #e2efda; border-bottom-color: #e2efda; font-weight: 600; }}
  .panel {{ display: none; padding: 0 12px 24px; overflow-x: auto; }}
  .panel.active {{ display: block; }}
  .chart-wrap {{ background: #fff; border: 1px solid #999; display: inline-block; min-width: 100%; }}
  .head-row, .student-row {{ display: flex; border-bottom: 1px solid #999; align-items: stretch; min-height: 36px; }}
  .head-row {{ background: #fff; font-size: 10px; font-weight: 600; position: sticky; top: 0; z-index: 3; }}
  .name-cell, .mg-cell, .day-head, .day-cell {{
    flex-shrink: 0; border-right: 1px solid #bbb; padding: 3px 4px;
  }}
  .name-cell {{ font-size: 12px; background: #f9f9f9; position: sticky; left: 0; z-index: 2;
    width: {name_w}px; min-width: {name_w}px; max-width: {name_w}px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .mg-cell {{ font-size: 11px; background: #f9f9f9; position: sticky; left: {name_w}px; z-index: 2;
    width: {mg_w}px; min-width: {mg_w}px; max-width: {mg_w}px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .track {{ display: flex; flex: 0 0 auto; }}
  .day-head, .day-cell {{ width: {cell_w}px; min-height: 34px; text-align: center; font-size: 9px;
    display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 1px; }}
  .student-row .day-cell {{ background: #c6e0b4; }}
  .day-cell.sp-range {{ background: #d9e8f7; }}
  .day-cell.session-done {{ background: #e8f4e8 !important; }}
  .day-cell.session-future {{ background: #fef9e7 !important; }}
  .sp-col {{ background: #ffe699 !important; }}
  .pill {{ font-size: 8px; padding: 1px 2px; border-radius: 2px; color: #fff; font-weight: 700; line-height: 1.15; }}
  .pill.step {{ background: #548235; min-width: 12px; }}
  .pill.sp_done {{ background: #7030a0; font-size: 7px; }}
  .pill.sa.done {{ background: #2e75b6; }}
  .pill.sa.scheduled {{ background: #fff; color: #2e75b6; border: 1px dashed #2e75b6; }}
  .pill.coach.done {{ background: #ed7d31; border: 1px solid #bf6920; }}
  .pill.coach.scheduled {{ background: #fff; color: #c55a11; border: 1px dashed #c55a11; }}
  .meta {{ font-size: 9px; color: #666; font-weight: normal; }}
  .note {{ padding: 8px 20px; font-size: 12px; color: #666; line-height: 1.6; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>コミットプラン: {html.escape(source)} ／ Lステップ: {html.escape(lstep_source)} ／ {len(rows)}名 ／ 集計基準日: {as_of.isoformat()}</p>
  <div class="legend">
    <span><span class="swatch range"></span> SPプログラム期間（STEP1〜完了）</span>
    <span><span class="swatch step"></span> STEP完了（数字）</span>
    <span><span class="swatch sp_done"></span> SPプログラム完了</span>
    <span><span class="swatch sa"></span> 自己分析（実施済）</span>
    <span><span class="swatch sa scheduled"></span> 自己分析（予定）</span>
    <span><span class="swatch coach"></span> 伴走（実施済）</span>
    <span><span class="swatch coach scheduled"></span> 伴走（予定）</span>
    <span><span class="swatch future-cell"></span> 予定セル背景</span>
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
  SP開始日 = SP開始日マスタ / Lステップ STEP1 / コミットプラン Q列。<br>
  自己分析 = コミットプラン W列 / 伴走 = X列（1回目）〜。<br>
  <strong>実施済</strong> = 集計基準日以前の日付 / <strong>予定</strong> = 基準日より未来（破線・薄黄セル）。<br>
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
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="実施済/予定の境界日（YYYY-MM-DD）。省略時は今日",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    if not args.xlsx.exists():
        print(f"Not found: {args.xlsx}", file=sys.stderr)
        return 1

    lstep_path = resolve_lstep_path(args.lstep)
    mg_short = load_lstep_mg_short_names(lstep_path) if lstep_path else {}
    lstep_index = None
    lstep_label = "(なし)"
    if lstep_path and lstep_path.exists():
        lstep_index = build_lstep_index(lstep_path, tokushin_only=False)
        lstep_label = str(lstep_path.relative_to(ROOT)) if lstep_path.is_relative_to(ROOT) else lstep_path.name
        print(f"Lステップ: {len(lstep_index)}名読込 ({lstep_label})")
    else:
        print("Warning: Lステップ not found", file=sys.stderr)

    df = pd.read_excel(args.xlsx, sheet_name="セッション実施状況管理", header=None)
    students = load_students(df, args.year, args.month, tokushin_only=True)
    sp_manual = load_sp_start_index(SP_START_PATH) if SP_START_PATH.exists() else {}
    if sp_manual:
        print(f"SP開始日マスタ: {len(sp_manual)}名 ({SP_START_PATH.name})")
    rows = build_timeline_rows(students, lstep_index, sp_manual, mg_short, as_of=as_of)
    if not rows:
        print("No rows with SP date", file=sys.stderr)
        return 1

    matched_lstep = sum(1 for r in rows if r["sp_src"] == "Lステップ")
    matched_manual = sum(1 for r in rows if r["sp_src"] == "SP開始日マスタ")
    title = f"セッション実施タイムライン（{args.year}年{args.month}月入会・新特進）"
    html_out = build_full_html(rows, title, args.xlsx.name, lstep_label, as_of)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_out, encoding="utf-8")
    print(f"Wrote {args.output} ({len(rows)} students, マスタ{matched_manual}名 / Lステップ{matched_lstep}名)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
