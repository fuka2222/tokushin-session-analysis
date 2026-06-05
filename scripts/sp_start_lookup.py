#!/usr/bin/env python3
"""セッション実施状況管理の SP開始日マスタ（手動更新・貼付取込）。"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data/metadata/sp_start_dates.tsv"

SKIP_NAME = re.compile(
    r"テスト|はるなテスト|もえこテスト|^$",
    re.I,
)


def norm_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("\u3000", "").replace(" ", "")
    s = re.sub(r"^[【\[][^】\]]+[】\]]", "", s)  # 【旧特進】等
    s = re.sub(r"[（(].*?[）)]", "", s)
    s = re.sub(r"[_　].*$", "", s)  # くりはら…さらりa組
    return s


def parse_sp_date(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s or s in ("-", "#REF!", "—"):
        return None
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s.replace(".", "/"))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def format_roster(d: date) -> str:
    return f"{d.year}/{d.month:02d}/{d.day:02d}"


def format_iso(d: date) -> str:
    return d.isoformat()


def load_sp_start_index(path: Path = DEFAULT_PATH) -> dict[str, date]:
    if not path.exists():
        return {}
    out: dict[str, date] = {}
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            name = (row.get("生徒名") or "").strip()
            if not name or SKIP_NAME.search(name):
                continue
            if (row.get("除外") or "").strip().lower() in ("1", "yes", "true"):
                continue
            d = parse_sp_date(row.get("SP開始日", ""))
            if d:
                out[norm_name(name)] = d
    return out


def lookup_sp_start(name: str, index: dict[str, date] | None = None) -> date | None:
    index = index if index is not None else load_sp_start_index()
    key = norm_name(name)
    if key in index:
        return index[key]
    for k, d in index.items():
        if key in k or k in key:
            if len(key) >= 3 and len(k) >= 3:
                return d
    return None


def names_match(a: str, b: str) -> bool:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    return na == nb or (len(na) >= 3 and len(nb) >= 3 and (na in nb or nb in na))
