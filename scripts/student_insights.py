"""生徒の進捗・可処分時間・9マス分類・注力優先度を算出。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

# 9マス定義（Coaching Session Design Playbook 準拠）
NINE_GRID = {
    1: {"name": "ロケット", "short": "①ロケット", "focus": "KPI・習慣化・振り返り構造化で負荷を上げる"},
    2: {"name": "エンジン強・目的地薄い", "short": "②目的地薄い", "focus": "価値観・ノーススター・本音の目標を深掘り"},
    3: {"name": "いい人・他人ゴール", "short": "③他人ゴール", "focus": "やらされ感の正体・内発的動機の発掘"},
    4: {"name": "熱いが詰まりやすい", "short": "④ブレーキ持ち", "focus": "最小行動・実験思考・完璧主義のブレーキ解除"},
    5: {"name": "平均的に前進", "short": "⑤平均前進", "focus": "振り返りの質・可視化・ピークステート"},
    6: {"name": "受け身の継続", "short": "⑥受け身", "focus": "放置コストと変化の快・決断を作る"},
    7: {"name": "燃えてるが聞かない", "short": "⑦我流", "focus": "7日間実験提案・進化としての変化"},
    8: {"name": "プライド防衛", "short": "⑧防衛", "focus": "事実ベースの現状把握・ごまかさない"},
    9: {"name": "漂流", "short": "⑨漂流", "focus": "コーチング契約の再確認・感情の糸口"},
}

TIME_QUADRANTS = {
    "high_high": {
        "label": "時間あり×進んでいる",
        "color": "green",
        "hypotheses": [],
    },
    "high_low": {
        "label": "時間あり×進んでいない",
        "color": "red",
        "hypotheses": [
            "虚偽報告の可能性",
            "具体的な進め方・参考リソースが不明",
            "完璧主義で手が止まっている",
            "ツール操作に時間を取られている",
            "課題で何が求められているか不明",
            "講師添削のハードルが高くクオリティにこだわりすぎ",
        ],
    },
    "low_high": {
        "label": "時間少×進んでいる",
        "color": "blue",
        "hypotheses": ["効率よく実行できている。習慣化の仕組みを横展開可能"],
    },
    "low_low": {
        "label": "時間少×進んでいない",
        "color": "orange",
        "hypotheses": [
            "可処分時間の確保自体が課題",
            "優先順位・スケジュール設計の見直しが必要",
        ],
    },
    "unknown": {
        "label": "データ不足",
        "color": "gray",
        "hypotheses": ["可処分時間または進捗データを入力してください"],
    },
}

# 週あたり可処分時間（時間）の閾値
TIME_HIGH_THRESHOLD = 8.0
# 進捗スコア 0-1 の閾値（step進捗・投稿等から算出）
PROGRESS_HIGH_THRESHOLD = 0.55


def _level(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip().lower()
    if v in ("高", "high", "h"):
        return "high"
    if v in ("中", "medium", "mid", "m"):
        return "mid"
    if v in ("低", "low", "l"):
        return "low"
    return None


def nine_grid_cell(coachable: str | None, goal: str | None) -> int | None:
    c, g = _level(coachable), _level(goal)
    if not c or not g:
        return None
    matrix = {
        ("high", "high"): 1,
        ("high", "mid"): 2,
        ("high", "low"): 3,
        ("mid", "high"): 4,
        ("mid", "mid"): 5,
        ("mid", "low"): 6,
        ("low", "high"): 7,
        ("low", "mid"): 8,
        ("low", "low"): 9,
    }
    return matrix.get((c, g))


def compute_progress_score(
    sp_day: int | None,
    step_at_session: str | None,
    first_post_done: bool | None,
    posts_count: int | None = None,
) -> float | None:
    """0-1 の進捗スコア（粗い推定）。"""
    if sp_day is None or sp_day < 0:
        return None
    score = 0.0
    if first_post_done:
        score += 0.5
    elif sp_day <= 30:
        # 30日以内なら経過日数で線形（14日→0.23）
        score += min(0.45, (sp_day / 30) * 0.45)
    if posts_count and posts_count > 0:
        score += min(0.3, posts_count * 0.05)
    if step_at_session:
        try:
            step = int(re.search(r"\d+", str(step_at_session)).group())  # type: ignore
            score += min(0.25, step / 48 * 0.25)
        except (AttributeError, ValueError):
            pass
    return min(1.0, score) if score > 0 else 0.05


def time_progress_quadrant(
    disposable_hours_week: float | None,
    time_used_hours_week: float | None,
    progress_score: float | None,
) -> dict[str, Any]:
    if disposable_hours_week is None or progress_score is None:
        return {**TIME_QUADRANTS["unknown"], "key": "unknown"}

    # 使えていない割合
    unused_ratio = None
    if disposable_hours_week > 0 and time_used_hours_week is not None:
        unused_ratio = max(0, 1 - time_used_hours_week / disposable_hours_week)

    time_high = disposable_hours_week >= TIME_HIGH_THRESHOLD
    prog_high = progress_score >= PROGRESS_HIGH_THRESHOLD

    if time_high and prog_high:
        key = "high_high"
    elif time_high and not prog_high:
        key = "high_low"
    elif not time_high and prog_high:
        key = "low_high"
    else:
        key = "low_low"

    out = {**TIME_QUADRANTS[key], "key": key}
    out["disposable_hours_week"] = disposable_hours_week
    out["time_used_hours_week"] = time_used_hours_week
    out["unused_ratio"] = unused_ratio
    out["progress_score"] = round(progress_score, 2)
    return out


def first_post_status(
    sp_start: str | None,
    first_post_date: str | None,
    today: datetime | None = None,
) -> dict[str, Any]:
    today = today or datetime.utcnow()
    if not sp_start:
        return {"status": "unknown", "label": "SP開始日不明", "days_to_deadline": None, "on_track": None}

    try:
        sp = datetime.strptime(sp_start[:10], "%Y-%m-%d")
    except ValueError:
        return {"status": "unknown", "label": "SP開始日不正", "days_to_deadline": None, "on_track": None}

    deadline = sp + timedelta(days=30)
    days_elapsed = (today.date() - sp.date()).days
    days_left = (deadline.date() - today.date()).days

    if first_post_date:
        try:
            fp = datetime.strptime(first_post_date[:10], "%Y-%m-%d")
            days_after = (fp.date() - sp.date()).days
            ok = days_after <= 30
            return {
                "status": "done",
                "label": f"初投稿済（SP+{days_after}日）",
                "days_to_deadline": days_left,
                "on_track": ok,
                "days_after_sp": days_after,
            }
        except ValueError:
            pass

    if days_elapsed > 30:
        return {
            "status": "overdue",
            "label": "30日超過・未投稿",
            "days_to_deadline": days_left,
            "on_track": False,
            "days_after_sp": days_elapsed,
        }
    if days_elapsed >= 22:
        return {
            "status": "at_risk",
            "label": f"残り{max(days_left,0)}日・要加速",
            "days_to_deadline": days_left,
            "on_track": False,
            "days_after_sp": days_elapsed,
        }
    return {
        "status": "in_progress",
        "label": f"進行中（SP+{days_elapsed}日）",
        "days_to_deadline": days_left,
        "on_track": True,
        "days_after_sp": days_elapsed,
    }


def priority_flags(student: dict[str, Any]) -> list[str]:
    flags = []
    fp = student.get("first_post") or {}
    tq = student.get("time_quadrant") or {}
    grid = student.get("nine_grid") or {}

    if fp.get("status") in ("overdue", "at_risk"):
        flags.append("初投稿30日")
    if tq.get("key") == "high_low":
        flags.append("時間多・進捗少")
    if grid.get("cell") in (6, 8, 9):
        flags.append(f"9マス{grid.get('short','')}")
    if student.get("evaluated_count", 0) == 0 and student.get("scheduled_count", 0) > 0:
        flags.append("未分析")
    if not student.get("mg_support_notes") and tq.get("key") == "high_low":
        flags.append("MG記入待ち")
    return flags
