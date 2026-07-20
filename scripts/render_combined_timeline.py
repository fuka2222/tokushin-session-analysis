#!/usr/bin/env python3
"""
特進コース全員 ＋ ベーシックコース（30日以内STEP18達成10名・未達成10名）を
1つのセッション実施タイムライン（グループ区切り付き）に描画する。

- 特進: コミットプラン由来のセッション（自己分析/伴走）＋Lステップ由来のSTEP進捗。
- ベーシック: セッション記録が無いため STEP進捗のみ（Lステップ「投稿プログラム(新)」CSV）。

用法:
  python3 scripts/render_combined_timeline.py
  python3 scripts/render_combined_timeline.py --basic-csv "~/Downloads/....csv" --as-of 2026-07-21
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_commit_plan_cohort import load_students  # noqa: E402
from lstep_sp_lookup import build_lstep_index, norm_name  # noqa: E402
from sp_start_lookup import load_sp_start_index  # noqa: E402
from render_session_gantt import (  # noqa: E402
    DEFAULT_XLSX,
    SP_START_PATH,
    build_timeline_rows,
    day_label,
    load_lstep_mg_short_names,
    pill_html,
    resolve_lstep_path,
    resolve_student_sheet,
    _session_cell_class,
)

ROOT = Path(__file__).resolve().parent.parent
# 特進「2026年4月入会・新特進」全員(約45名)を再現できるスナップショット。
# 新しい (9).xlsx は4月特進が整理され10名に減るため、公開版と同じ6月3日集計を既定にする。
DEFAULT_TOKUSHIN_XLSX = Path.home() / "Downloads" / "コミットプラン 2026年6月3日集計.xlsx"
DEFAULT_BASIC_CSV = Path.home() / "Downloads" / "Lステップの顧客データ - 投稿プログラム（新） (1).csv"
DEFAULT_POSTS_CSV = Path.home() / "Downloads" / "Lステップの顧客データ - 投稿数.csv"
DEFAULT_OUT = ROOT / "data/reports/combined_session_timeline.html"

GROUP_TOKUSHIN = "特進コース（全員）"
GROUP_BASIC_ACH = "ベーシックコース｜初投稿30日以内 達成"
GROUP_BASIC_NON = "ベーシックコース｜初投稿30日以内 未達成"


# ----------------------------- basic cohort -----------------------------
def _pdate(s: str) -> date | None:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        return None


def load_basic_records(csv_path: Path) -> list[dict]:
    raw = list(csv.reader(csv_path.open(encoding="utf-8")))
    hdr = raw[0]
    si = {h: i for i, h in enumerate(hdr)}
    course_idx = [i for i, h in enumerate(hdr) if h == "コース"][0]
    step_cols = [(n, si[f"STEP{n}完了日"]) for n in range(1, 20)]
    out = []
    for r in raw[1:]:
        course = (r[course_idx] or "").replace("講座_", "").strip()
        if "ベーシック" not in course:
            continue
        start = _pdate(r[si["投稿プログラム開始日"]])
        if not start:
            continue
        step_dates = [(n, _pdate(r[c])) for n, c in step_cols]
        step_dates = [(n, d) for n, d in step_dates if d]
        s18 = next((d for n, d in step_dates if n == 18), None)
        s19 = next((d for n, d in step_dates if n == 19), None)
        out.append(
            {
                "name": r[si["表示名"]].replace("　", " ").strip(),
                "klass": (r[si["クラス名(講師名)"]] or "").strip(),
                "mg": (r[si["担当MG名"]] or "").strip(),
                "sp": start,
                "step_dates": step_dates,
                "step18": s18,
                "step19": s19,
                "day18": (s18 - start).days if s18 else None,
            }
        )
    return out


def load_program_index(csv_path: Path) -> dict[str, dict]:
    """投稿プログラム(新)CSV → 表示名(norm) → 最新STEP完了日など（全コース）。"""
    raw = list(csv.reader(csv_path.open(encoding="utf-8")))
    hdr = raw[0]
    si = {h: i for i, h in enumerate(hdr)}
    step_cols = [(n, si[f"STEP{n}完了日"]) for n in range(1, 20)]
    idx: dict[str, dict] = {}
    for r in raw[1:]:
        name = r[si["表示名"]].replace("　", " ").strip()
        if not name:
            continue
        start = _pdate(r[si["投稿プログラム開始日"]])
        step_dates = [(n, _pdate(r[c])) for n, c in step_cols]
        step_dates = [(n, d) for n, d in step_dates if d]
        if not step_dates and not start:
            continue
        idx[norm_name(name)] = {
            "sp": start,
            "step_dates": step_dates,
            "step18": next((d for n, d in step_dates if n == 18), None),
            "step19": next((d for n, d in step_dates if n == 19), None),
        }
    return idx


def refresh_steps(row: dict, prog_index: dict[str, dict]) -> None:
    """行のSTEP/SP完了イベントを最新CSVで上書き（SP開始日=既存のまま、セッションは非変更）。"""
    hit = prog_index.get(norm_name(row["name"]))
    if not hit:
        k = norm_name(row["name"])
        hit = next((v for kk, v in prog_index.items() if k and (k in kk or kk in k)), None)
    if not hit or not hit["step_dates"]:
        return
    sp = row["sp"]
    row["events"] = [e for e in row["events"] if e["kind"] not in ("step", "sp_done")]
    for n, d in hit["step_dates"]:
        row["events"].append({"day": (d - sp).days, "kind": "step", "label": f"STEP{n}"})
    last_n, last_d = hit["step_dates"][-1]
    sp_complete = hit["step19"] or last_d
    row["sp_complete_day"] = (sp_complete - sp).days
    row["latest_step"] = last_n
    if last_n >= 19 and row["sp_complete_day"] >= 0:
        row["events"].append({"day": row["sp_complete_day"], "kind": "sp_done", "label": f"SP完了(STEP{last_n})"})
    s18 = hit["step18"]
    row["day18"] = (s18 - sp).days if s18 else None


def _spread_by_class(pool: list[dict], k: int, day_sort) -> list[dict]:
    """クラス（講師）横断でk名を代表抽出（ラウンドロビン・決定的）。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in sorted(pool, key=lambda x: (x["klass"], day_sort(x), x["name"])):
        groups[rec["klass"]].append(rec)
    classes = sorted(groups)
    picked: list[dict] = []
    i = 0
    while len(picked) < k and any(groups.values()):
        cls = classes[i % len(classes)]
        if groups[cls]:
            picked.append(groups[cls].pop(0))
        i += 1
        if i > len(classes) * 200:
            break
    return picked[:k]


def select_basic_cohort(records: list[dict], as_of: date, n_each: int = 10):
    window_start = as_of - timedelta(days=30)
    achievers = [r for r in records if r["day18"] is not None and 0 <= r["day18"] <= 30]
    non = [
        r
        for r in records
        if r["sp"] <= window_start and not (r["day18"] is not None and 0 <= r["day18"] <= 30)
    ]
    # 達成: 早い順に代表 / 未達成: SP開始が古く猶予のあった順に代表
    ach_sel = _spread_by_class(achievers, n_each, day_sort=lambda x: x["day18"])
    non_sel = _spread_by_class(non, n_each, day_sort=lambda x: (x["sp"] - as_of).days)
    return ach_sel, non_sel, len(achievers), len(non)


def basic_to_row(rec: dict, as_of: date) -> dict:
    sp = rec["sp"]
    events = []
    for n, d in rec["step_dates"]:
        events.append({"day": (d - sp).days, "kind": "step", "label": f"STEP{n}"})
    sp_complete = rec["step19"] or (rec["step_dates"][-1][1] if rec["step_dates"] else None)
    sp_complete_day = (sp_complete - sp).days if sp_complete else None
    latest_step = rec["step_dates"][-1][0] if rec["step_dates"] else 0
    if sp_complete and sp_complete_day is not None and sp_complete_day >= 0 and latest_step >= 19:
        events.append({"day": sp_complete_day, "kind": "sp_done", "label": f"SP完了(STEP{latest_step})"})
    mg_display = rec["mg"] or (rec["klass"] and f"{rec['klass']}") or ""
    return {
        "name": rec["name"],
        "mg": mg_display,
        "sp": sp,
        "sp_src": "Lステップ",
        "sp_complete_day": sp_complete_day,
        "latest_step": latest_step,
        "events": events,
        "sa_gap": None,
        "day18": rec["day18"],
    }


# ----------------------------- posts (実投稿) -----------------------------
def load_post_index(csv_path: Path) -> dict[str, dict]:
    """Lステップ「投稿数」CSV → 表示名(norm) → 実投稿日リスト・本数・IGアカウント。"""
    raw = list(csv.reader(csv_path.open(encoding="utf-8")))
    hdr = raw[0]
    si = {h: i for i, h in enumerate(hdr)}
    post_cols = [(n, si[f"{n}投稿目完了日"]) for n in range(1, 61) if f"{n}投稿目完了日" in si]
    url_i = si.get("InstagramアカウントURL")
    idx: dict[str, dict] = {}
    for r in raw[1:]:
        name = r[si["表示名"]].replace("　", " ").strip()
        if not name:
            continue
        posts = [(n, _pdate(r[c])) for n, c in post_cols]
        posts = [(n, d) for n, d in posts if d]
        idx[norm_name(name)] = {
            "posts": posts,
            "n": len(posts),
            "url": (r[url_i].strip() if url_i is not None else ""),
        }
    return idx


def attach_posts(row: dict, post_index: dict[str, dict]) -> None:
    """行に実投稿イベント・本数・実初投稿日数を付与する。"""
    sp = row["sp"]
    hit = post_index.get(norm_name(row["name"]))
    if not hit:
        for k in norm_name(row["name"]),:
            hit = next((v for kk, v in post_index.items() if k and (k in kk or kk in k)), None)
    row["n_posts"] = hit["n"] if hit else 0
    row["ig_url"] = hit["url"] if hit else ""
    first_day = None
    if hit:
        for n, d in hit["posts"]:
            day = (d - sp).days
            row["events"].append({"day": day, "kind": "post", "label": f"投稿{n}", "n": n, "date": d})
            if n == 1:
                first_day = day
    row["first_post_day"] = first_day


def _pill(e: dict) -> str:
    if e.get("kind") == "post":
        title = f'{e["label"]}（{e["date"].isoformat()}）'
        return f'<span class="pill post" title="{html.escape(title)}">{e["n"]}</span>'
    return pill_html(e)


# ----------------------------- rendering -----------------------------
def render_panel_grouped(groups: list[tuple[str, list[dict]]], max_day: int, name_w: int, mg_w: int, cell_w: int) -> str:
    total_w = name_w + mg_w + (max_day + 1) * cell_w

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
        # 同一セル内の並び: STEP → SP完了 → 自己分析/伴走 → 投稿
        order = {"step": 0, "sp_done": 1, "sa": 2, "coach": 3, "post": 4}
        parts = []
        for d in range(max_day + 1):
            evs = sorted(by_day.get(d, []), key=lambda e: order.get(e["kind"], 9))
            inner = "".join(_pill(e) for e in evs)
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
        <div class="mg-cell" style="width:{mg_w}px">MG / クラス</div>
        <div class="track">{header_cells()}</div>
      </div>
    """
    body = ""
    for gi, (label, rows) in enumerate(groups):
        gcls = ["g-tok", "g-ach", "g-non"][gi % 3]
        course = "tok" if gi == 0 else "basic"
        body += (
            f'<div class="group-row {gcls}" data-g="{gi}" style="width:{total_w}px">'
            f'{html.escape(label)}　<span class="gcount">{len(rows)}名</span></div>'
        )
        for r in rows:
            meta = ""
            if r.get("latest_step"):
                meta = f' <span class="meta">STEP{r["latest_step"]}</span>'
            elif r.get("sp_src") == "Lステップ":
                meta = ' <span class="meta">SP未着手</span>'
            d18 = r.get("day18")
            res = ""
            achieve = "non"
            if d18 is not None and 0 <= d18 <= 30:
                res = f'<span class="res ok">初投稿{d18}日</span>'
                achieve = "ach"
            elif d18 is not None:
                res = f'<span class="res slow">初投稿{d18}日</span>'
                achieve = "slow"
            elif label.startswith("ベーシック"):
                res = '<span class="res ng">初投稿未</span>'
            n_posts = r.get("n_posts", 0)
            fpd = r.get("first_post_day")
            if n_posts:
                fp = f'・実{fpd}日' if fpd is not None else ""
                post_meta = f'<span class="posts yes">投稿{n_posts}本{fp}</span>'
            else:
                post_meta = '<span class="posts no">投稿0</span>'
            has_session = 1 if any(e["kind"] in ("sa", "coach") for e in r["events"]) else 0
            body += f"""
      <div class="student-row" data-g="{gi}" data-course="{course}" data-achieve="{achieve}" data-session="{has_session}">
        <div class="name-cell" style="width:{name_w}px">{html.escape(r['name'])}{meta}{res}{post_meta}</div>
        <div class="mg-cell" style="width:{mg_w}px">{html.escape(r['mg'])}</div>
        <div class="track">{row_cells(r)}</div>
      </div>"""
    return head + body + "</div>"


def build_html(groups: list[tuple[str, list[dict]]], title: str, subtitle: str, as_of: date) -> str:
    name_w, mg_w, cell_w = 190, 96, 32
    all_rows = [r for _, rows in groups for r in rows]
    sp_max = max((r["sp_complete_day"] or 0 for r in all_rows), default=30)
    sp_max = max(sp_max + 3, 30)
    p1 = render_panel_grouped(groups, 30, name_w, mg_w, cell_w)
    p2 = render_panel_grouped(groups, sp_max, name_w, mg_w, cell_w)
    p3 = render_panel_grouped(groups, 60, name_w, mg_w, cell_w)

    # サマリ（グループ別 初投稿中央値）
    def med18(rows):
        xs = sorted(r["day18"] for r in rows if r.get("day18") is not None)
        if not xs:
            return "—"
        m = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
        return f"{m:g}日 (n={len(xs)})"

    summary = " ／ ".join(f"{lbl.split('｜')[-1] if '｜' in lbl else lbl}: 初投稿中央値 {med18(rows)}" for lbl, rows in groups)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif; margin: 0; background: #f5f5f5; }}
  header {{ padding: 16px 20px; background: #fff; border-bottom: 1px solid #ddd; }}
  header h1 {{ margin: 0 0 6px; font-size: 18px; }}
  header p {{ margin: 0; font-size: 13px; color: #555; }}
  .summary {{ margin-top: 6px; font-size: 12.5px; color: #333; font-weight: 600; }}
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
  .head-row, .student-row {{ display: flex; border-bottom: 1px solid #999; align-items: stretch; min-height: 36px; }}
  .head-row {{ background: #fff; font-size: 10px; font-weight: 600; position: sticky; top: 0; z-index: 3; }}
  .group-row {{ font-size: 12px; font-weight: 700; padding: 5px 10px; border-bottom: 1px solid #999;
    position: sticky; left: 0; color: #fff; }}
  .group-row .gcount {{ font-weight: 500; opacity: .9; font-size: 11px; }}
  .group-row.g-tok {{ background: #7030a0; }}
  .group-row.g-ach {{ background: #548235; }}
  .group-row.g-non {{ background: #c55a11; }}
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
  .pill.post {{ background: #e84393; min-width: 12px; border: 1px solid #c2185b; }}
  .meta {{ font-size: 9px; color: #666; font-weight: normal; }}
  .posts {{ font-size: 9px; font-weight: 700; margin-left: 4px; }}
  .posts.yes {{ color: #c2185b; }}
  .posts.no {{ color: #b0b0b0; }}
  .filters {{ padding: 10px 20px; background: #fbfbfb; border-bottom: 1px solid #eee; display: flex; gap: 22px; flex-wrap: wrap; font-size: 12.5px; }}
  .filters fieldset {{ border: none; margin: 0; padding: 0; display: flex; align-items: center; gap: 8px; }}
  .filters legend {{ float: none; font-weight: 700; color: #444; margin-right: 4px; padding: 0; }}
  .filters label {{ display: inline-flex; align-items: center; gap: 3px; cursor: pointer; }}
  .filters input {{ cursor: pointer; }}
  .res {{ font-size: 9px; font-weight: 700; margin-left: 4px; padding: 0 3px; border-radius: 2px; }}
  .res.ok {{ color: #2f6b1f; background: #e2efda; }}
  .res.slow {{ color: #a9641a; background: #fdf0d9; }}
  .res.ng {{ color: #a04000; background: #fde9d9; }}
  .note {{ padding: 8px 20px; font-size: 12px; color: #666; line-height: 1.6; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>{html.escape(subtitle)} ／ 集計基準日: {as_of.isoformat()}</p>
  <p class="summary">{html.escape(summary)}</p>
  <div class="legend">
    <span><span class="swatch range"></span> SPプログラム期間（STEP1〜完了）</span>
    <span><span class="swatch step"></span> STEP完了（数字）</span>
    <span><span class="swatch sp_done"></span> SPプログラム完了</span>
    <span><span class="swatch sa"></span> 自己分析</span>
    <span><span class="swatch coach"></span> 伴走（コーチング）</span>
    <span><span class="swatch" style="background:#e84393;border:1px solid #c2185b"></span> 実投稿（数字＝○本目）</span>
  </div>
</header>
<div class="filters">
  <fieldset>
    <legend>コース</legend>
    <label><input type="radio" name="fc" value="all" checked onchange="applyFilter()">すべて</label>
    <label><input type="radio" name="fc" value="tok" onchange="applyFilter()">特進</label>
    <label><input type="radio" name="fc" value="basic" onchange="applyFilter()">ベーシック</label>
  </fieldset>
  <fieldset>
    <legend>初投稿(STEP18)</legend>
    <label><input type="radio" name="fa" value="all" checked onchange="applyFilter()">すべて</label>
    <label><input type="radio" name="fa" value="ach" onchange="applyFilter()">30日以内 達成</label>
    <label><input type="radio" name="fa" value="notach" onchange="applyFilter()">未達成（30日超・未到達）</label>
  </fieldset>
  <fieldset>
    <legend>セッション</legend>
    <label><input type="radio" name="fs" value="all" checked onchange="applyFilter()">すべて</label>
    <label><input type="radio" name="fs" value="1" onchange="applyFilter()">あり</label>
    <label><input type="radio" name="fs" value="0" onchange="applyFilter()">なし</label>
  </fieldset>
  <span id="fcount" style="align-self:center;color:#666;font-weight:600"></span>
</div>
<div class="tabs">
  <button class="tab active" onclick="show('p1', this)">SP〜30日（序盤）</button>
  <button class="tab" onclick="show('p2', this)">SPプログラム期間（〜{sp_max}日）</button>
  <button class="tab" onclick="show('p3', this)">SP〜60日（コーチング）</button>
</div>
<div id="p1" class="panel active">{p1}</div>
<div id="p2" class="panel">{p2}</div>
<div id="p3" class="panel">{p3}</div>
<p class="note">
  特進コース = セッション（自己分析=コミットプラン W列 / 伴走=X列〜）＋ STEP進捗。<br>
  ベーシックコース = セッション記録が無いため <strong>STEP進捗のみ</strong>。10名ずつをクラス（講師）横断で代表抽出。<br>
  SP開始日 = Lステップ「投稿プログラム開始日」（0日目）。「初投稿◯日」= STEP18到達までの日数。
</p>
<script>
function show(id, btn) {{
  document.querySelectorAll('.panel,.tab').forEach(e => e.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
function val(name) {{ return document.querySelector('input[name="'+name+'"]:checked').value; }}
function applyFilter() {{
  var fc = val('fc'), fa = val('fa'), fs = val('fs');
  var uniq = {{}};
  document.querySelectorAll('.panel.active .student-row').forEach(function(row) {{
    var c = row.dataset.course, ach = row.dataset.achieve, ses = row.dataset.session;
    var okC = (fc === 'all') || (c === fc);
    var okA = (fa === 'all') || (fa === 'ach' && ach === 'ach') ||
              (fa === 'notach' && (ach === 'non' || ach === 'slow'));
    var okS = (fs === 'all') || (ses === fs);
    var show = okC && okA && okS;
    row.style.display = show ? '' : 'none';
    if (show) uniq[row.querySelector('.name-cell').textContent] = 1;
  }});
  // 全パネルに同じ表示/非表示を反映
  document.querySelectorAll('.student-row').forEach(function(row) {{
    var c = row.dataset.course, ach = row.dataset.achieve, ses = row.dataset.session;
    var okC = (fc === 'all') || (c === fc);
    var okA = (fa === 'all') || (fa === 'ach' && ach === 'ach') ||
              (fa === 'notach' && (ach === 'non' || ach === 'slow'));
    var okS = (fs === 'all') || (ses === fs);
    row.style.display = (okC && okA && okS) ? '' : 'none';
  }});
  // 空グループの見出しを隠す
  document.querySelectorAll('.group-row').forEach(function(g) {{
    var gi = g.dataset.g, panel = g.closest('.panel');
    var any = panel.querySelectorAll('.student-row[data-g="'+gi+'"]:not([style*="display: none"])').length;
    g.style.display = any ? '' : 'none';
  }});
  document.getElementById('fcount').textContent = '表示中 ' + Object.keys(uniq).length + ' 名';
}}
document.querySelectorAll('.tab').forEach(function(t) {{ t.addEventListener('click', function() {{ setTimeout(applyFilter, 0); }}); }});
applyFilter();
</script>
</body>
</html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?", type=Path, default=DEFAULT_TOKUSHIN_XLSX)
    ap.add_argument("--lstep", type=Path, default=None)
    ap.add_argument("--basic-csv", type=Path, default=DEFAULT_BASIC_CSV)
    ap.add_argument("--posts-csv", type=Path, default=DEFAULT_POSTS_CSV)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=4)
    ap.add_argument("--as-of", type=str, default=None)
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    # ---- 特進 ----
    lstep_path = resolve_lstep_path(args.lstep)
    mg_short = load_lstep_mg_short_names(lstep_path) if lstep_path else {}
    lstep_index = build_lstep_index(lstep_path, tokushin_only=False) if lstep_path and lstep_path.exists() else None
    sheet = resolve_student_sheet(args.xlsx)
    df = pd.read_excel(args.xlsx, sheet_name=sheet, header=None)
    students = load_students(df, args.year, args.month, tokushin_only=True)
    sp_manual = load_sp_start_index(SP_START_PATH) if SP_START_PATH.exists() else {}
    tok_rows = build_timeline_rows(students, lstep_index, sp_manual, mg_short, as_of=as_of)
    # 特進のSTEP進捗を最新CSVで上書き（セッションはコミットプランのまま維持）
    basic_csv0 = Path(str(args.basic_csv)).expanduser()
    prog_index = load_program_index(basic_csv0) if basic_csv0.exists() else {}
    refreshed = 0
    for r in tok_rows:
        before = r.get("latest_step")
        refresh_steps(r, prog_index)
        if r.get("latest_step") != before or r.get("day18") is not None:
            refreshed += 1
    # 上書きされなかった行のday18も再設定（STEP18イベントから）
    for r in tok_rows:
        if "day18" not in r:
            s18 = next((e["day"] for e in r["events"] if e.get("label") == "STEP18"), None)
            r["day18"] = s18
    print(f"特進: {len(tok_rows)}名（STEP最新化 {refreshed}名）")

    # ---- ベーシック ----
    basic_csv = Path(str(args.basic_csv)).expanduser()
    recs = load_basic_records(basic_csv)
    ach, non, n_ach, n_non = select_basic_cohort(recs, as_of, n_each=10)
    ach_rows = [basic_to_row(r, as_of) for r in ach]
    non_rows = [basic_to_row(r, as_of) for r in non]
    ach_rows.sort(key=lambda r: (r["mg"], r["name"]))
    non_rows.sort(key=lambda r: (r["mg"], r["name"]))
    print(f"ベーシック達成: {len(ach_rows)}/{n_ach}名  未達成: {len(non_rows)}/{n_non}名（母集団から抽出）")

    # ---- 実投稿（全コース共通・名前突合）----
    posts_csv = Path(str(args.posts_csv)).expanduser()
    post_index = load_post_index(posts_csv) if posts_csv.exists() else {}
    for r in tok_rows + ach_rows + non_rows:
        attach_posts(r, post_index)
    posted = sum(1 for r in tok_rows + ach_rows + non_rows if r.get("n_posts"))
    print(f"実投稿: {posted}/{len(tok_rows)+len(ach_rows)+len(non_rows)}名が投稿あり（{posts_csv.name}）")

    groups = [
        (GROUP_TOKUSHIN, tok_rows),
        (GROUP_BASIC_ACH, ach_rows),
        (GROUP_BASIC_NON, non_rows),
    ]
    title = "セッション実施タイムライン｜特進 全員 ＋ ベーシック（達成/未達成 各10名）"
    subtitle = f"コミットプラン: {args.xlsx.name} ／ Lステップ(基本): {basic_csv.name}"
    out_html = build_html(groups, title, subtitle, as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(out_html, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
