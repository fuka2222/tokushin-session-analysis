#!/usr/bin/env python3
"""
残日数 × SP進捗（STEP）の危険度スキャッター＋アラート一覧を出力する。

- 見込みライン = 30日以内STEP18達成者の中央値ペース（残日数=30−中央値到達日）。理想の参照線。
- 対策相談ライン = 到達可能性ライン。残りSTEPを「1日あたり paceステップ」で終えられるか。
    残日数 < (18 − 現STEP) / pace → 対策相談ゾーン（アラート）。paceは画面で切替（既定2）。
- 対象 = 進行中の全生徒（SP開始からの経過日数 0〜29日、STEP18未達）。

用法:
  python3 scripts/render_risk_scatter.py [--as-of 2026-07-18] [--csv <投稿プログラム(新).csv>] [-o docs/risk.html]
"""
from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import re
import statistics
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = Path.home() / "Downloads" / "Lステップの顧客データ - 投稿プログラム（新） (1).csv"
DEFAULT_LITE_CSV = Path.home() / "Downloads" / "Lステップの顧客データ - 投稿プログラム（2026年6月〜）.csv"
DEFAULT_OUT = ROOT / "data/reports/risk_scatter.html"


def _pd(s: str) -> date | None:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        return None


def _norm(s: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", s.strip().replace("　", "").replace(" ", "")).lower()


def _parse_program_csv(path: Path) -> dict:
    """投稿プログラム（新 or 2026年6月〜lite）を読み、表示名→{start, steps:{大STEP:date}} を返す。
    新: 列 STEP{n}完了日 → 大STEP=n。lite: 列 STEP{x}-{y}完了日 → 大STEP=x（サブの最遅日で完了）。"""
    if not path.exists():
        return {}
    raw = list(csv.reader(path.open(encoding="utf-8")))
    hdr = raw[0]
    si = {h: i for i, h in enumerate(hdr)}
    start_col = si.get("投稿プログラム開始日", si.get("プログラム開始日"))
    course_i = next((i for i, h in enumerate(hdr) if h == "コース"), None)
    # 大STEP -> [列index]
    bigcols: dict[int, list[int]] = collections.defaultdict(list)
    for i, h in enumerate(hdr):
        m = re.match(r"STEP(\d+)(?:-(\d+))?完了日", h)
        if m:
            bigcols[int(m.group(1))].append(i)
    out: dict[str, dict] = {}
    for r in raw[1:]:
        name = (r[si["表示名"]] if "表示名" in si else "").replace("　", " ").strip()
        if not name:
            continue
        start = _pd(r[start_col]) if start_col is not None else None
        steps: dict[int, date] = {}
        for big, cols in bigcols.items():
            ds = [_pd(r[c]) for c in cols]
            ds = [d for d in ds if d]
            if ds:
                steps[big] = max(ds)  # その大STEPを完了した日
        rec = {
            "name": name,
            "course": (r[course_i] or "").replace("講座_", "").strip() if course_i is not None else "",
            "klass": (r[si["クラス名(講師名)"]] or "").strip() if "クラス名(講師名)" in si else "",
            "mg": (r[si["担当MG名"]] or "").strip() if "担当MG名" in si else "",
            "start": start,
            "steps": steps,
        }
        out[_norm(name)] = rec
    return out


def load(csv_path: Path, as_of: date, lite_path: Path | None = None):
    new_idx = _parse_program_csv(csv_path)
    lite_idx = _parse_program_csv(lite_path) if lite_path else {}
    # マージ: 同名は「進捗(大STEP最大)が大きい方 / start がある方」を採用
    keys = set(new_idx) | set(lite_idx)
    rows = []
    for k in keys:
        a, b = new_idx.get(k), lite_idx.get(k)
        cands = [c for c in (a, b) if c and c["start"]]
        if not cands:
            continue
        rec = max(cands, key=lambda c: (max(c["steps"], default=0), len(c["steps"])))
        course = rec["course"] or (a or b or {}).get("course", "")
        tag = "特進" if "特進" in course else ("基本" if "ベーシック" in course else None)
        if not tag:
            continue
        start = rec["start"]
        steps = {n: d for n, d in rec["steps"].items()}
        rows.append(
            {
                "tag": tag,
                "start": start,
                "steps": steps,
                "s18": steps.get(18),
                "name": rec["name"],
                "klass": rec["klass"],
                "mg": rec["mg"],
            }
        )

    # 見込みライン: クリーンな30日以内達成者の中央値到達日
    ach = [
        x
        for x in rows
        if x["s18"]
        and 0 <= (x["s18"] - x["start"]).days <= 30
        and min((v - x["start"]).days for v in x["steps"].values()) >= 0
    ]
    med_day = collections.defaultdict(list)
    for x in ach:
        for n, dt in x["steps"].items():
            if n <= 18:
                med_day[n].append((dt - x["start"]).days)
    med = {n: statistics.median(v) for n, v in med_day.items()}

    def interp_med(S):
        if S in med:
            return med[S]
        ks = sorted(med)
        if S < ks[0]:
            return med[ks[0]]
        if S >= ks[-1]:
            return med[ks[-1]]
        lo = max(k for k in ks if k <= S)
        hi = min(k for k in ks if k >= S)
        return med[lo] + (S - lo) / (hi - lo) * (med[hi] - med[lo])

    medline = [{"step": s, "rem": round(30 - interp_med(s), 2)} for s in range(0, 19)]

    # 生徒レコード（特進のみ）: STEP完了日とSP開始日を持たせ、時点計算はJSで行う
    students = []
    for x in rows:
        if x["tag"] != "特進":
            continue
        students.append(
            {
                "name": x["name"],
                "course": x["tag"],
                "klass": x["klass"],
                "mg": x["mg"],
                "start": x["start"].isoformat(),
                "steps": sorted([[n, d.isoformat()] for n, d in x["steps"].items()]),
            }
        )
    starts = [s["start"] for s in students]
    return medline, students, len(ach), (min(starts) if starts else None), (max(starts) if starts else None)


def best_snapshot(students, as_of: date, min_start: str) -> str:
    """着手済(STEP>=1)で窓内の特進が最も多い日を既定基準日にする。"""
    if not students:
        return as_of.isoformat()
    parsed = [(date.fromisoformat(s["start"]), [date.fromisoformat(d) for _, d in s["steps"]]) for s in students]
    start = date.fromisoformat(min_start)
    best, best_d = -1, as_of
    d = start
    while d <= as_of:
        c = 0
        for st, sd in parsed:
            E = (d - st).days
            if 0 <= E < 30 and any(x <= d for x in sd):
                c += 1
        if c > best:
            best, best_d = c, d
        d = date.fromordinal(d.toordinal() + 1)
    return best_d.isoformat()


def build_html(medline, students, n_ach: int, as_of: date, csv_name: str, min_start: str, max_start: str) -> str:
    payload = json.dumps({"medline": medline, "students": students}, ensure_ascii=False)
    today = as_of.isoformat()
    default_snap = best_snapshot(students, as_of, min_start)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>残日数 × SP進捗 危険度スキャッター</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Hiragino Sans","Yu Gothic",Meiryo,sans-serif; margin:0; background:#f5f5f5; color:#222; }}
  header {{ padding:16px 20px; background:#fff; border-bottom:1px solid #ddd; }}
  h1 {{ margin:0 0 6px; font-size:18px; }}
  header p {{ margin:0; font-size:13px; color:#555; }}
  .legend {{ display:flex; gap:16px; margin-top:10px; font-size:12px; flex-wrap:wrap; }}
  .legend span {{ display:inline-flex; align-items:center; gap:5px; }}
  .sw {{ width:14px; height:14px; border-radius:50%; display:inline-block; }}
  .controls {{ padding:12px 20px; background:#fbfbfb; border-bottom:1px solid #eee; display:flex; gap:24px; flex-wrap:wrap; font-size:13px; align-items:center; }}
  .controls fieldset {{ border:none; margin:0; padding:0; display:flex; align-items:center; gap:8px; }}
  .controls legend {{ float:none; font-weight:700; color:#444; padding:0; margin-right:4px; }}
  .controls label {{ display:inline-flex; align-items:center; gap:3px; cursor:pointer; }}
  .wrap {{ padding:16px 20px 40px; max-width:1180px; }}
  .card {{ background:#fff; border:1px solid #e2e2e2; border-radius:10px; padding:12px; margin-bottom:20px; overflow-x:auto; }}
  svg {{ display:block; width:100%; height:auto; max-width:900px; margin:0 auto; }}
  .pt {{ cursor:pointer; }}
  .ptlabel {{ font-size:9px; fill:#c0392b; }}
  .alerts h2 {{ font-size:15px; margin:0 0 8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ padding:7px 10px; text-align:left; border-bottom:1px solid #eee; white-space:nowrap; }}
  th {{ font-size:11px; color:#888; text-transform:uppercase; letter-spacing:.03em; background:#fafafa; }}
  td.rem {{ font-weight:700; color:#c0392b; font-variant-numeric:tabular-nums; }}
  td.step {{ font-variant-numeric:tabular-nums; }}
  .none {{ color:#bbb; }}
  #tt {{ position:fixed; z-index:50; pointer-events:none; background:#fff; border:1px solid #ccc; border-radius:8px;
    padding:8px 10px; font-size:12px; box-shadow:0 6px 20px rgba(0,0,0,.16); opacity:0; transition:opacity .1s; max-width:240px; }}
  #tt .nm {{ font-weight:800; margin-bottom:3px; }}
  .cnt {{ font-weight:700; }}
  .note {{ font-size:12px; color:#666; line-height:1.6; margin-top:4px; }}
</style>
</head>
<body>
<nav style="background:#2c3e50;padding:8px 20px;font-size:13px"><a href="./" style="color:#fff;text-decoration:none;margin-right:16px">📊 統合タイムライン</a><a href="./risk.html" style="color:#f1c40f;text-decoration:none;font-weight:700">⚠️ 危険度スキャッター（このページ）</a></nav>
<header>
  <h1>残日数 × SP進捗　危険度スキャッター（特進コース）</h1>
  <p>残日数 = (SP開始日+30日) − <b>基準日</b>　／　横軸 = <b>基準日時点</b>の完了STEP　／　見込みライン=STEP18達成者{n_ach}名の中央値ペース　／　データ: {html.escape(csv_name)}（新+lite統合）</p>
  <div class="legend">
    <span><span class="sw" style="background:#e67e22"></span>見込みゾーン</span>
    <span><span class="sw" style="background:#e74c3c"></span>対策相談ゾーン（アラート）</span>
    <span><span class="sw" style="background:#e67e22;border-radius:2px;width:20px;height:0;border-top:2px dashed #e67e22"></span>見込みライン（達成者中央値＝理想ペース）</span>
    <span><span class="sw" style="background:#e74c3c;border-radius:2px;width:20px;height:3px"></span>対策相談ライン（到達可能性）</span>
  </div>
</header>
<div class="controls">
  <fieldset><legend>基準日（過去の時点も見られる）</legend>
    <button type="button" onclick="shiftDay(-7)">◀7日</button>
    <button type="button" onclick="shiftDay(-1)">◀1日</button>
    <input type="date" id="snapd" min="{min_start}" max="{today}" value="{default_snap}" onchange="draw()">
    <button type="button" onclick="shiftDay(1)">1日▶</button>
    <button type="button" onclick="shiftDay(7)">7日▶</button>
    <button type="button" onclick="document.getElementById('snapd').value='{today}';draw()">今日</button>
  </fieldset>
  <fieldset><legend>到達可能性ペース（1日あたりSTEP）</legend>
    <label><input type="radio" name="p" value="1" onchange="draw()">1</label>
    <label><input type="radio" name="p" value="1.5" onchange="draw()">1.5</label>
    <label><input type="radio" name="p" value="2" checked onchange="draw()">2</label>
    <label><input type="radio" name="p" value="3" onchange="draw()">3</label>
  </fieldset>
  <label><input type="checkbox" id="hide0" checked onchange="draw()">未着手(STEP0)を隠す</label>
  <span class="cnt" id="cnt"></span>
</div>
<div class="wrap">
  <div class="card"><svg id="chart" viewBox="0 0 900 560" role="img" aria-label="残日数×SP進捗スキャッター"></svg>
    <p class="note">縦=残日数（30−SP開始からの経過日数）、横=現在の完了STEP。点が<b>対策相談ライン</b>より下＝残り日数で残りSTEPを終えられない見込み。同座標の点は横に少しずらして表示。</p>
  </div>
  <div class="card alerts">
    <h2>🔴 対策相談ゾーンの生徒（残日数の少ない順）</h2>
    <table><thead><tr><th>生徒名</th><th>コース</th><th>所属クラス</th><th>担当MG名</th><th>現STEP</th><th>残日数</th></tr></thead>
    <tbody id="alertbody"></tbody></table>
  </div>
</div>
<div id="tt"></div>
<script>
const DATA = {payload};
const M = {{t:24,r:20,b:44,l:44}}, W=900, H=560;
const iw=W-M.l-M.r, ih=H-M.t-M.b;
const X = s => M.l + s/18*iw;
const Y = r => M.t + (30-r)/30*ih;
const DAY = 86400000;
function val(n){{return document.querySelector('input[name="'+n+'"]:checked').value;}}
function feasRem(step, pace){{ return (18-step)/pace; }}
function shiftDay(n){{
  const el=document.getElementById('snapd'); const d=new Date(el.value+'T00:00:00');
  d.setDate(d.getDate()+n);
  const iso=d.toISOString().slice(0,10);
  if(iso>=el.min && iso<=el.max) el.value=iso;
  draw();
}}
// 基準日時点の各生徒の状態（残日数・現STEP）を計算。窓外(0-30日外)や達成済みは除外。
function snapshotRows(snapISO){{
  const snap=new Date(snapISO+'T00:00:00');
  const out=[]; let step0=0, achieved=0;
  DATA.students.forEach(s=>{{
    const start=new Date(s.start+'T00:00:00');
    const E=Math.floor((snap-start)/DAY);
    if(E<0 || E>=30) return;                 // その時点で30日窓の外
    let cur=0, done=false;
    s.steps.forEach(([n,iso])=>{{ const d=new Date(iso+'T00:00:00');
      if(d<=snap){{ if(n>cur) cur=n; if(n>=18) done=true; }} }});
    if(done){{ achieved++; return; }}          // その時点で既に初投稿(STEP18)達成
    out.push({{name:s.name, course:s.course, klass:s.klass, mg:s.mg, step:cur, rem:30-E}});
  }});
  out._step0 = out.filter(p=>p.step===0).length;
  out._achieved = achieved;
  return out;
}}

function draw(){{
  const pace=parseFloat(val('p')), hide0=document.getElementById('hide0').checked;
  const snapISO=document.getElementById('snapd').value;
  const svg=document.getElementById('chart');
  const all = snapshotRows(snapISO);
  const nStep0 = all._step0;
  let rows = hide0 ? all.filter(p => p.step!==0) : all;
  // zone polygons
  const feasPts=[]; for(let s=0;s<=18;s++) feasPts.push([X(s), Y(Math.min(30,feasRem(s,pace)))]);
  let dangerPoly = `M${{M.l}},${{Y(0)}} `;
  for(let s=0;s<=18;s++) dangerPoly += `L${{X(s)}},${{Y(Math.min(30,feasRem(s,pace)))}} `;
  dangerPoly += `L${{X(18)}},${{Y(0)}} Z`;
  const medPoly = DATA.medline.map((d,i)=>`${{i?'L':'M'}}${{X(d.step)}},${{Y(d.rem)}}`).join(' ');
  const feasLine = feasPts.map((p,i)=>`${{i?'L':'M'}}${{p[0]}},${{p[1]}}`).join(' ');
  // grid + ticks
  let g='';
  for(let r=0;r<=30;r+=2){{ const y=Y(r); g+=`<line x1="${{M.l}}" y1="${{y}}" x2="${{W-M.r}}" y2="${{y}}" stroke="#eee"/>`+
    `<text x="${{M.l-6}}" y="${{y+3}}" text-anchor="end" font-size="9" fill="#999">${{r}}</text>`; }}
  for(let s=0;s<=18;s++){{ const x=X(s); g+=`<line x1="${{x}}" y1="${{M.t}}" x2="${{x}}" y2="${{H-M.b}}" stroke="#f1f1f1"/>`+
    `<text x="${{x}}" y="${{H-M.b+14}}" text-anchor="middle" font-size="9" fill="#999">${{s}}</text>`; }}
  // points with jitter for same coord
  const seen={{}}; let pts=''; const dangers=[];
  rows.forEach(p=>{{
    const key=p.step+'_'+p.rem; const k=(seen[key]=(seen[key]||0)+1);
    const off=((k-1)%6)*6 - 15; // 横ジッタ
    const danger = p.rem < feasRem(p.step, pace);
    const cx=X(p.step)+off, cy=Y(p.rem);
    const col = danger? '#e74c3c':'#e67e22';
    pts += `<circle class="pt" cx="${{cx}}" cy="${{cy}}" r="5" fill="${{col}}" fill-opacity="0.85" stroke="#fff" stroke-width="1"`+
           ` data-n="${{encodeURIComponent(p.name)}}" data-c="${{p.course}}" data-k="${{encodeURIComponent(p.klass)}}"`+
           ` data-m="${{encodeURIComponent(p.mg)}}" data-s="${{p.step}}" data-r="${{p.rem}}"/>`;
    if(danger){{ dangers.push(p);
      if(k<=1) pts += `<text class="ptlabel" x="${{cx}}" y="${{cy-7}}" text-anchor="middle">${{p.name}}</text>`; }}
  }});
  const zoneLabels = `<text x="${{W-M.r-14}}" y="${{M.t+30}}" text-anchor="end" font-size="20" font-weight="800" fill="#e67e22" opacity="0.5">見込みゾーン</text>`+
    `<text x="${{M.l+14}}" y="${{H-M.b-16}}" font-size="20" font-weight="800" fill="#e74c3c" opacity="0.6">対策相談ゾーン</text>`;
  svg.innerHTML = g +
    `<path d="${{dangerPoly}}" fill="#e74c3c" fill-opacity="0.07"/>`+
    `<path d="${{medPoly}}" fill="none" stroke="#e67e22" stroke-width="2" stroke-dasharray="5 4"/>`+
    `<path d="${{feasLine}}" fill="none" stroke="#e74c3c" stroke-width="2.5"/>`+
    `<rect x="${{M.l}}" y="${{M.t}}" width="${{iw}}" height="${{ih}}" fill="none" stroke="#e67e22"/>`+
    zoneLabels + pts +
    `<text x="${{M.l+iw/2}}" y="${{H-6}}" text-anchor="middle" font-size="11" fill="#666">SP進捗（完了STEP）</text>`+
    `<text transform="translate(12,${{M.t+ih/2}}) rotate(-90)" text-anchor="middle" font-size="11" fill="#666">残日数</text>`;
  attachHover();
  // alerts
  dangers.sort((a,b)=>a.rem-b.rem);
  document.getElementById('alertbody').innerHTML = dangers.map(p=>
    `<tr><td>${{p.name}}</td><td>${{p.course}}</td><td>${{p.klass||'<span class=none>—</span>'}}</td>`+
    `<td>${{p.mg||'<span class=none>—</span>'}}</td><td class="step">STEP${{p.step}}</td><td class="rem">残${{p.rem}}日</td></tr>`).join('')
    || '<tr><td colspan="6" class="none">該当なし</td></tr>';
  document.getElementById('cnt').textContent =
    `基準日 ${{snapISO}}｜窓内 ${{all.length}}名 表示 ${{rows.length}}名 ／ 🔴対策相談 ${{dangers.length}}名`
    + (hide0 ? ` ／ 未着手STEP0 ${{nStep0}}名を非表示` : '')
    + `（＋この時点で達成済 ${{all._achieved}}名）`;
}}
function attachHover(){{
  const tt=document.getElementById('tt');
  document.querySelectorAll('.pt').forEach(c=>{{
    c.addEventListener('mouseenter',e=>{{
      const d=c.dataset;
      tt.innerHTML=`<div class="nm">${{decodeURIComponent(d.n)}}</div>`+
        `<div>${{d.c}} / ${{decodeURIComponent(d.k)||'—'}}</div>`+
        `<div>担当MG: ${{decodeURIComponent(d.m)||'—'}}</div>`+
        `<div>現STEP${{d.s}} ・ 残${{d.r}}日</div>`;
      tt.style.opacity=1;
    }});
    c.addEventListener('mousemove',e=>{{ tt.style.left=(e.clientX+14)+'px'; tt.style.top=(e.clientY+14)+'px'; }});
    c.addEventListener('mouseleave',()=>{{ tt.style.opacity=0; }});
  }});
}}
draw();
</script>
</body>
</html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--lite-csv", type=Path, default=DEFAULT_LITE_CSV)
    ap.add_argument("--as-of", type=str, default=None, help="残日数の基準日（省略時=今日）")
    ap.add_argument("--course", type=str, default="特進", help="既定表示コース（特進/基本/all）")
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    csv_path = Path(str(args.csv)).expanduser()
    lite_path = Path(str(args.lite_csv)).expanduser()
    medline, students, n_ach, min_start, max_start = load(csv_path, as_of, lite_path)
    print(f"特進 生徒 {len(students)}名（STEP完了日付き）/ 達成者(見込み基準) {n_ach}名 / SP開始 {min_start}〜{max_start}")
    out = build_html(medline, students, n_ach, as_of, csv_path.name, min_start or "2026-05-01", max_start or as_of.isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(out, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
