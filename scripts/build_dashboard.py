#!/usr/bin/env python3
"""SQLite + ロスター + 結果JSON → ダッシュボード用 data.json を生成。"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboard"
ROSTER_PATH = ROOT / "data" / "metadata" / "roster_paste.tsv"
PROFILES_PATH = ROOT / "data" / "metadata" / "student_profiles.csv"
LSTEP_PATH = ROOT / "data" / "metadata" / "lstep_progress.csv"
SP_START_PATH = ROOT / "data" / "metadata" / "sp_start_dates.tsv"

import sys

sys.path.insert(0, str(ROOT / "scripts"))
from db import HEARING_KEYS, connect  # noqa: E402
from student_insights import (  # noqa: E402
    NINE_GRID,
    compute_progress_score,
    first_post_status,
    nine_grid_cell,
    priority_flags,
    time_progress_quadrant,
)
from sp_start_lookup import load_sp_start_index, lookup_sp_start  # noqa: E402

BLOCK_LABELS = {
    "A1": "挨拶・役割", "A2": "本日の流れ", "A3": "MG自己紹介", "A4": "生徒自己紹介",
    "A5": "傾聴・家族", "A6": "入会きっかけ", "A7": "学習状況",
    "B1": "講師とMGの役割", "B2": "初速・完了主義", "B3": "マインドセット",
    "C1": "セッション回数", "C2": "参加・遅刻ルール", "C3": "日報・返信",
    "D1": "半年目標", "D2": "SP開始・初投稿", "D3": "目標シート", "D4": "次回日程",
    "D5": "タスク具体化", "D6": "日報フォーマット", "E1": "クロージング",
    "01": "アイスブレイク", "02": "現状確認", "03": "課題明確化", "04": "目標再認識",
    "05": "タスク明確化", "06": "決意表明", "07": "クロージング",
}

SESSION_SLOT_LABELS = ["1回目", "2回目", "3回目", "4回目", "5回目", "6回目", "7回目", "8回目", "9回目"]
SESSION_COL_KEYS = [str(i) for i in range(9)]  # 列0〜8


def parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s or "1900" in s:
        return None
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s.replace(".", "/"))
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def to_hiragana(s: str) -> str:
    """カタカナ→ひらがな（突合用）。"""
    out = []
    for c in s or "":
        o = ord(c)
        if 0x30A1 <= o <= 0x30F6:
            out.append(chr(o - 0x60))
        else:
            out.append(c)
    return "".join(out)


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", to_hiragana(name or "")).lower()


def names_match(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def user_id_match(roster_uid: str, eval_sid: str) -> bool:
    """@hiroruka と ルカ など。"""
    uid = (roster_uid or "").lstrip("@").lower()
    sid = normalize_name(eval_sid)
    if not uid or not sid:
        return False
    return sid in uid or uid in sid


def load_detail(result_path: str | None) -> dict | None:
    if not result_path:
        return None
    path = ROOT / result_path
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("structure") or data


def load_profiles() -> dict[str, dict]:
    if not PROFILES_PATH.exists():
        return {}
    out: dict[str, dict] = {}
    for row in csv.DictReader(PROFILES_PATH.open(encoding="utf-8")):
        name = (row.get("roster_name") or "").strip()
        if name:
            out[normalize_name(name)] = row
    return out


def load_lstep() -> dict[str, dict]:
    """表示名（正規化）→ Lステップ進捗。management_id でも引ける。"""
    if not LSTEP_PATH.exists():
        return {}
    out: dict[str, dict] = {}
    for row in csv.DictReader(LSTEP_PATH.open(encoding="utf-8")):
        name = (row.get("display_name") or "").strip()
        if name:
            out[normalize_name(name)] = row
        mid = (row.get("management_id") or "").strip()
        if mid:
            out[f"id:{mid}"] = row
    return out


def find_lstep(student_name: str, lstep: dict[str, dict]) -> dict | None:
    key = normalize_name(student_name)
    if key in lstep:
        return lstep[key]
    for k, row in lstep.items():
        if k.startswith("id:"):
            continue
        if names_match(student_name, row.get("display_name", "")):
            return row
    return None


def _float(val: str | None) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def enrich_student(
    student: dict,
    profile: dict | None,
    lstep_row: dict | None = None,
) -> dict:
    """初投稿・時間×進捗・9マス・注力フラグを付与。"""
    p = profile or {}
    ls = lstep_row or {}
    ev = student.get("latest_evaluation") or {}
    hearing = ev.get("hearing") or {}

    sp_start = (
        student.get("sp_start_date")
        or (p.get("sp_start_date") or "").strip()
        or None
    )
    if not sp_start:
        manual = lookup_sp_start(student.get("student_name") or "", None)
        if manual:
            sp_start = manual.isoformat()
    if not sp_start:
        sp_start = (ls.get("sp_start_lstep") or "").strip() or None
    if sp_start == "":
        sp_start = None
    if sp_start and not student.get("sp_start_date"):
        student["sp_start_date"] = sp_start

    first_post_date = (p.get("first_post_date") or "").strip() or None
    if not first_post_date:
        lfp = (ls.get("first_post_date") or "").strip()
        first_post_date = lfp or None

    posts_count = None
    try:
        pc = ls.get("post_count")
        if pc is not None and str(pc).strip() != "":
            posts_count = int(pc)
    except ValueError:
        posts_count = None

    sp_days = None
    if sp_start and student.get("first_session_date"):
        try:
            a = datetime.strptime(sp_start[:10], "%Y-%m-%d").date()
            b = datetime.strptime(student["first_session_date"][:10], "%Y-%m-%d").date()
            sp_days = (b - a).days
        except ValueError:
            pass

    disposable = _float(p.get("disposable_hours_week"))
    time_used = _float(p.get("time_used_hours_week"))
    coachable = p.get("coachable_level") or ""
    goal = p.get("goal_level") or ""

    step = hearing.get("step_at_session", {}).get("value") or p.get("step_at_session")
    if not step and ls.get("latest_step"):
        step = f"STEP{ls.get('latest_step')}"
    fp_done = first_post_date is not None
    progress = compute_progress_score(sp_days, step, fp_done, posts_count)

    cell = nine_grid_cell(coachable, goal)
    grid_info = None
    if cell:
        g = NINE_GRID[cell]
        grid_info = {
            "cell": cell,
            "name": g["name"],
            "short": g["short"],
            "focus": g["focus"],
            "coachable_level": coachable,
            "goal_level": goal,
        }

    student["attributes"] = {
        "age": p.get("age") or hearing.get("age", {}).get("value"),
        "occupation": p.get("occupation") or hearing.get("occupation", {}).get("value"),
        "video_experience": p.get("video_experience") or hearing.get("computer_literacy", {}).get("value"),
        "has_pc": p.get("has_pc"),
        "genre": p.get("genre") or student.get("genre"),
    }
    student["disposable_hours_week"] = disposable
    student["time_used_hours_week"] = time_used
    student["mg_support_notes"] = (p.get("mg_support_notes") or "").strip()
    student["first_post"] = first_post_status(sp_start, first_post_date)
    student["time_quadrant"] = time_progress_quadrant(disposable, time_used, progress)
    student["nine_grid"] = grid_info
    student["priority_flags"] = priority_flags(student)
    student["needs_attention"] = len(student["priority_flags"]) > 0
    if ls:
        student["lstep"] = {
            "management_id": ls.get("management_id"),
            "steps_completed": _float(ls.get("steps_completed")),
            "latest_step": ls.get("latest_step"),
            "latest_step_date": ls.get("latest_step_date"),
            "first_post_date": ls.get("first_post_date") or None,
            "post_count": posts_count,
            "program_start_date": ls.get("program_start_date") or None,
            "imported_at": ls.get("imported_at"),
        }
    return student


def load_roster() -> list[dict]:
    if not ROSTER_PATH.exists():
        return []
    rows = []
    for row in csv.DictReader(ROSTER_PATH.open(encoding="utf-8"), delimiter="\t"):
        name = (row.get("生徒名") or "").strip()
        if not name or name.startswith("【重複】") or "テスト" in name:
            continue
        scheduled = []
        first = parse_date(row.get("1回目通常セッション", ""))
        for i, col in enumerate(SESSION_COL_KEYS):
            d = parse_date(row.get(col, ""))
            if not d and i == 0 and first:
                d = first
            scheduled.append(
                {
                    "slot": i,
                    "label": SESSION_SLOT_LABELS[i] if i < len(SESSION_SLOT_LABELS) else f"{i+1}回目",
                    "date": d,
                }
            )
        rows.append(
            {
                "student_name": name,
                "user_id": (row.get("user ID") or "").strip(),
                "notion_url": (row.get("生徒ページ") or "").strip(),
                "teacher": (row.get("講師") or "").strip(),
                "class_name": (row.get("クラス名") or "").strip(),
                "mentor": (row.get("メンター") or "").strip(),
                "sp_start_date": parse_date(row.get("SP開始日", "")),
                "first_session_date": first,
                "support_end_date": parse_date(row.get("最終サポート日", "")),
                "mg_name": (row.get("担当MG名") or "").strip(),
                "scheduled_sessions": scheduled,
            }
        )
    return rows


def eval_index(evaluations: list[dict]) -> dict[tuple[str, int], dict]:
    idx: dict[tuple[str, int], dict] = {}
    for e in evaluations:
        sid = e["student_id"]
        sn = int(e["session_number"])
        for key in [sid]:
            idx[(key, sn)] = e
        # ロスター名とも突合
        for r_name in [sid]:
            idx[(r_name, sn)] = e
    return idx


def find_eval(
    student_name: str,
    session_number: int,
    evaluations: list[dict],
    user_id: str = "",
) -> dict | None:
    for e in evaluations:
        if int(e.get("session_number", 0)) != session_number:
            continue
        sid = e.get("student_id", "")
        if names_match(student_name, sid) or user_id_match(user_id, sid):
            return e
    return None


def build() -> Path:
    conn = connect()
    sessions = [dict(r) for r in conn.execute("SELECT * FROM session_evaluations ORDER BY evaluated_at DESC")]

    hearing_map: dict[tuple, dict] = {}
    for r in conn.execute(
        "SELECT student_id, session_number, field_key, value, confidence FROM hearing_fields"
    ):
        key = (r["student_id"], r["session_number"])
        hearing_map.setdefault(key, {})[r["field_key"]] = {
            "value": r["value"],
            "confidence": r["confidence"],
        }
    conn.close()

    enriched_evals = []
    for s in sessions:
        detail = load_detail(s.get("result_json_path"))
        hk = hearing_map.get((s["student_id"], s["session_number"]), {})
        enriched_evals.append({**s, "hearing": hk, "blocks": (detail or {}).get("blocks") or {}})

    roster = load_roster()
    profiles = load_profiles()
    lstep = load_lstep()
    students: list[dict] = []
    seen_names: set[str] = set()

    today = datetime.now(timezone.utc).date()

    for r in roster:
        seen_names.add(normalize_name(r["student_name"]))
        slots = []
        evaluated_count = 0
        adherence_rates = []

        for i, slot in enumerate(r["scheduled_sessions"]):
            sn = i + 1  # 1回目 = slot 0
            ev = find_eval(r["student_name"], sn, enriched_evals, r.get("user_id", ""))
            date_str = slot["date"]
            status = "empty"
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d").date()
                    status = "done" if d <= today else "scheduled"
                except ValueError:
                    status = "scheduled"

            adherence = None
            likelihood = None
            if ev:
                status = "analyzed"
                evaluated_count += 1
                adherence = ev.get("structure_adherence_rate")
                likelihood = ev.get("script_delivery_likelihood")
                if adherence is not None:
                    adherence_rates.append(adherence)

            slots.append(
                {
                    **slot,
                    "session_number": sn,
                    "status": status,
                    "adherence": adherence,
                    "likelihood": likelihood,
                    "has_evaluation": ev is not None,
                }
            )

        scheduled_count = sum(1 for s in slots if s["date"])
        overall_adherence = (
            round(sum(adherence_rates) / len(adherence_rates), 3) if adherence_rates else None
        )

        latest_ev = None
        for sn in range(12, 0, -1):
            latest_ev = find_eval(r["student_name"], sn, enriched_evals, r.get("user_id", ""))
            if latest_ev:
                break

        st = {
            **r,
            "session_slots": slots,
            "scheduled_count": scheduled_count,
            "evaluated_count": evaluated_count,
            "overall_adherence": overall_adherence,
            "latest_evaluation": latest_ev,
            "genre": (latest_ev or {}).get("hearing", {}).get("genre", {}).get("value"),
        }
        prof = profiles.get(normalize_name(r["student_name"]))
        ls = find_lstep(r["student_name"], lstep)
        students.append(enrich_student(st, prof, ls))

    # ロスターに無い評価のみの生徒
    for e in enriched_evals:
        sid = e["student_id"]
        if any(names_match(sid, s["student_name"]) for s in students):
            continue
        sn = int(e["session_number"])
        slots = [
            {
                "slot": i,
                "label": SESSION_SLOT_LABELS[i] if i < len(SESSION_SLOT_LABELS) else f"{i+1}回目",
                "date": e.get("session_date"),
                "session_number": i + 1,
                "status": "analyzed" if i + 1 == sn else "empty",
                "adherence": e.get("structure_adherence_rate") if i + 1 == sn else None,
                "likelihood": e.get("script_delivery_likelihood") if i + 1 == sn else None,
                "has_evaluation": i + 1 == sn,
            }
            for i in range(9)
        ]
        st = {
            "student_name": sid,
            "user_id": "",
            "class_name": "",
            "teacher": "",
            "mentor": "",
            "mg_name": e.get("mg_name", ""),
            "sp_start_date": e.get("sp_start_date"),
            "first_session_date": e.get("session_date"),
            "support_end_date": None,
            "scheduled_sessions": [],
            "session_slots": slots,
            "scheduled_count": 1,
            "evaluated_count": 1,
            "overall_adherence": e.get("structure_adherence_rate"),
            "latest_evaluation": e,
            "genre": e.get("hearing", {}).get("genre", {}).get("value"),
        }
        ls = find_lstep(sid, lstep)
        students.append(enrich_student(st, None, ls))

    students.sort(
        key=lambda x: (not x.get("needs_attention"), x.get("first_session_date") or ""),
        reverse=False,
    )
    # needs_attention を上に（False < True なので reverse=False で attention first は needs_attention True を先に）
    students.sort(key=lambda x: not x.get("needs_attention"))

    rates = [s["structure_adherence_rate"] for s in sessions if s.get("structure_adherence_rate") is not None]
    likelihood = [s.get("script_delivery_likelihood") for s in sessions]

    mg_stats: dict[str, dict] = {}
    for s in sessions:
        mg = s.get("mg_name") or "（未設定）"
        mg_stats.setdefault(mg, {"mg_name": mg, "count": 0, "rates": [], "high": 0})
        mg_stats[mg]["count"] += 1
        if s.get("structure_adherence_rate") is not None:
            mg_stats[mg]["rates"].append(s["structure_adherence_rate"])
        if s.get("script_delivery_likelihood") == "high":
            mg_stats[mg]["high"] += 1

    mg_list = sorted(
        [
            {
                "mg_name": m["mg_name"],
                "count": m["count"],
                "adherence_mean": round(sum(m["rates"]) / len(m["rates"]), 3) if m["rates"] else None,
                "high_rate": round(m["high"] / m["count"], 2) if m["count"] else 0,
            }
            for m in mg_stats.values()
        ],
        key=lambda x: (-(x["adherence_mean"] or 0), -x["count"]),
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "block_labels": BLOCK_LABELS,
        "hearing_keys": HEARING_KEYS,
        "summary": {
            "total_students": len(students),
            "total_evaluations": len(sessions),
            "roster_count": len(roster),
            "lstep_count": sum(1 for _ in lstep if not str(_).startswith("id:")),
            "needs_attention_count": sum(1 for s in students if s.get("needs_attention")),
            "adherence_mean": round(sum(rates) / len(rates), 3) if rates else None,
            "high_count": sum(1 for x in likelihood if x == "high"),
            "medium_count": sum(1 for x in likelihood if x == "medium"),
            "low_count": sum(1 for x in likelihood if x == "low"),
        },
        "nine_grid_legend": NINE_GRID,
        "time_quadrant_legend": ["high_high", "high_low", "low_high", "low_low"],
        "mg_stats": mg_list,
        "students": students,
        "sessions": enriched_evals,
    }

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out = DASHBOARD_DIR / "data.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> None:
    path = build()
    print(f"ダッシュボードデータ: {path}")
    print("表示: python scripts/serve_dashboard.py")


if __name__ == "__main__":
    main()
