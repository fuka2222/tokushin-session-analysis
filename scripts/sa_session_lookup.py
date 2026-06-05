#!/usr/bin/env python3
"""Notion「自己分析セッション（手動格納）」CSV から自己分析実施者を引く。"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from lstep_sp_lookup import norm_name, parse_date

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data/metadata/sa_sessions_notion.csv"

SKIP_NAMES = {"自己分析セッション", "自己分析", ""}

# 表示名ゆれ → コミットプラン/Lステップ名
NAME_ALIASES: dict[str, str] = {
    "ごうだい（くりはら）あきこさん": "くりはらあきこ（ごうだいあきこ）",
    "🟠のづじゅん": "のづじゅん",
    "おかもとまこさん": "おかもとまこ",
    "かたひらゆみさん": "かたひら　ゆみ",
    "あらかきゆかさん": "あらかきゆか",
    "やましたゆりかさん": "やましたゆりか",
    "わたなべともこ(りんこ)": "わたなべ　ともこ（わたなべりんこ）",
    "おおつぼ_かおり": "おおつぼかおり",
    "おだかめぐみ 自己分析一緒にうめた": "おだか めぐみ",
    "とりなりちえみ": "とみなりちえみ",
    "せきさちよ": "せきね　ちひろ",
    "やまもとひさの": "やまぎしりえ",
    "ふじもとえり_": "ふじもとえり",
    "やすながのぞみ_": "やすなが　のぞみ",
    "たかだあとむ_": "タカダアトム",
    "はやし　ななか": "はやし ななか",
    "ひらいで ちえこ": "ひらいでちえこ",
    "このぶゆか": "このぶ　ゆか",
    "ななみみほ": "ななみ　みほ",
    "はらしまはやと": "はらしま　はやと",
    "あかしひさき": "あかし　ひさき",
    "いわさきじゅんこ": "いわさき　じゅんこ",
    "しいはら まいこ": "しいはらまいこ",
    "くりすひでこ": "くりす　ひでこ",
    "つじむらなぎさ": "なつやま　みか",
    "かつのりきよこ": "かつのり　きよこ",
    "ちゃえん しょうご": "ちゃえんしょうご",
    "のまさちえ": "のま　さちえ",
    "きむらあや": "きむら　あや",
    "はまだまゆみ": "はまだまゆみ",
    "あめみやかな": "あめみや　かな",
    "いざわあさみ": "いざわ　あさみ",
    "かわいゆきえ": "かわい ゆきえ",
    "すぎやまみお": "すぎやまみお",
    "いしまるまこ": "いしまるまこ",
    "くろきみう": "くろきみう",
    "おぐりみきこ": "おぐり　みきこ",
}


def clean_student_name(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^[🟠🔴🟡🟢🔵⚪️\s]+", "", s)
    s = re.sub(r"(さん|様|_|自己分析.*)$", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return NAME_ALIASES.get(raw.strip(), NAME_ALIASES.get(s, s))


def norm_staff(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    # 表記ゆれ統一
    mapping = {
        "fuka": "森本風花",
        "森本風花（ふうか）": "森本風花",
        "森淳子（そたか）": "森淳子",
        "中富 智弘": "中富智弘",
        "中富智弘": "中富智弘",
        "森本風花": "森本風花",
        "小野芹那": "小野芹那",
        "野村ゆか": "野村ゆか",
    }
    return mapping.get(s, s)


def parse_notion_date(val) -> date | None:
    if not val:
        return None
    s = str(val).strip().strip('"')
    # "April 12, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", s)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
            return dt.date()
        except ValueError:
            pass
    return parse_date(val)


def load_sa_sessions(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            name_raw = (raw.get("生徒名") or "").strip()
            if not name_raw or name_raw in SKIP_NAMES:
                continue
            name = clean_student_name(name_raw)
            staff = norm_staff(raw.get("自己分析実施者") or "")
            session_date = parse_notion_date(raw.get("面談実施日"))
            coach_mg = (raw.get("伴走担当者") or "").strip()
            rows.append(
                {
                    "display_name": name,
                    "norm_name": norm_name(name),
                    "sa_staff": staff,
                    "sa_session_date": session_date,
                    "coach_mg_notion": coach_mg,
                    "sheet_url": (raw.get("自己分析シート URL") or "").strip(),
                }
            )
    return rows


def build_sa_index(path: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for row in load_sa_sessions(path):
        key = row["norm_name"]
        if key not in index:
            index[key] = row
        else:
            # より新しい面談日を優先
            old = index[key]
            if row["sa_session_date"] and (
                not old["sa_session_date"] or row["sa_session_date"] > old["sa_session_date"]
            ):
                index[key] = row
    return index


def lookup_sa(index: dict[str, dict], commit_name: str) -> dict | None:
    from lstep_sp_lookup import lookup_lstep

    return lookup_lstep(index, commit_name)
