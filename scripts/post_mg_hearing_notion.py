#!/usr/bin/env python3
"""MGヒアリング（11月卒業投稿数）を Notion に KFF 形式で投稿する。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HEARING = ROOT / "data/metadata/mg_hearing_graduation_posts.tsv"
DEFAULT_GRAD = ROOT / "data/reports/monthly_20260604/commit_graduation_posts.csv"
DEFAULT_PAGE = "36ff3b0f-ba85-80f7-bba6-eb68b100ff70"  # 卒業時60投稿目標

NOTION_VERSION = "2022-06-28"
CHUNK = 90


def rt(text: str, *, bold: bool = False) -> dict:
    obj: dict = {"type": "text", "text": {"content": text[:2000]}}
    if bold:
        obj["annotations"] = {"bold": True}
    return obj


def para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [rt(text)]}}


def h(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": [rt(text)]}}


def bullet(text: str, bold_prefix: str = "") -> dict:
    parts = []
    if bold_prefix:
        parts.append(rt(bold_prefix, bold=True))
        parts.append(rt(text))
    else:
        parts.append(rt(text))
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": parts}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def callout(text: str, emoji: str = "📌") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [rt(text)],
            "icon": {"type": "emoji", "emoji": emoji},
        },
    }


def table_block(headers: list[str], rows: list[list[str]]) -> dict:
    cells = []
    for row in [headers, *rows]:
        cells.append(
            {
                "type": "table_row",
                "table_row": {
                    "cells": [[rt(c)] for c in row],
                },
            }
        )
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(headers),
            "has_column_header": True,
            "has_row_header": False,
            "children": cells,
        },
    }


def load_hearing(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_grad(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["生徒名"].replace(" ", "")
            out[name] = row
    return out


def tier(posts: int) -> str:
    if posts >= 60:
        return "60+"
    if posts >= 31:
        return "31-59"
    return "≤30"


def factor_tags(row: dict) -> list[str]:
    text = " ".join(
        row.get(k, "") or ""
        for k in ("成功要因（要約）", "MG・伴走サポート（要約）", "障壁・ペース調整", "生徒の言葉・詳細メモ")
    )
    tags: list[str] = []
    rules = [
        ("毎日投稿", ("毎日", "毎回")),
        ("動機・覚悟", ("覚悟", "辞め", "執着", "最後", "家族", "もったいない", "ガッツ", "フルスロットル")),
        ("次アクション計画", ("次", "宣言", "5分", "1週間", "計画", "約束投稿")),
        ("スケジュール共設", ("スケジュール", "時間の使い方", "撮影編集")),
        ("ペースダウン", ("ペースダウン", "質重視", "無理に数")),
        ("講師連携", ("講師", "1on1", "添削", "FB")),
        ("ライフイベント/メンタル", ("結婚", "引越", "退職", "流産", "夜勤", "メンタル", "休職", "通院", "精神")),
        ("方向性・ジャンル", ("ジャンル", "方向性", "TTP", "顔出し", "転換")),
        ("初速遅れ", ("初投稿", "3ヶ月")),
        ("自走力", ("自走", "自分で継続", "ゴリゴリ")),
        ("褒め・期待管理", ("褒め", "期待")),
        ("インスタ外サポート", ("個別チャット", "今日の◎", "おしゃべり")),
    ]
    for label, keys in rules:
        if any(k in text for k in keys):
            tags.append(label)
    return tags or ["（タグ未分類）"]


def mg_support_patterns(rows: list[dict]) -> list[tuple[str, int, str]]:
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for row in rows:
        sup = row.get("MG・伴走サポート（要約）", "") or ""
        if not sup or sup == "（詳細記載少）":
            continue
        for part in sup.split(";"):
            part = part.strip()
            if part:
                counter[part] += 1
                examples.setdefault(part, row["生徒名"])
    return [(k, v, examples[k]) for k, v in counter.most_common()]


def build_kff_draft(rows: list[dict], n_total: int, n_hearing: int) -> list[str]:
    high = [r for r in rows if int(r["卒業時投稿数"]) >= 60]
    low = [r for r in rows if int(r["卒業時投稿数"]) <= 30]

    lines = [
        f"【Fact】11月コミット卒業23名のうち60投稿達成は6名（26.1%）。MGヒアリングは{n_hearing}/{n_total}名分（中間）。",
        "【Finding 1】高投稿層（60+）は「毎日投稿前提の覚悟」＋MGによる「宣言・スケジュール・ペース調整」のセットが共通。",
        "【Finding 2】中〜低層ではライフイベント・メンタル、講師FB/方向性の不一致、初投稿遅延、時間不足がボトルネック。",
        "【Finding 3】「次アクション計画（5分→1週間）」は低層でも有効だが、時間確保（休職等）がないと限界。",
        "【Finding 4】フォロワー数と投稿数は一致しない（いとう: 7万F・34投稿）。指標設計に注意。",
        "【Action 1】初回〜5回目で「次回までの宣言＋撮影編集スケジュール」を全MG標準化（森本・うちだ型）。",
        "【Action 2】講師FB遅延・方向性不一致はMGが早期エスカレーション（おざわ・ふじい型の再発防止）。",
        "【Action 3】メンタル・ライフイベント時はインスタ外チャットで関係維持→復帰後に目標再設定（なめかわ型）。",
        "【Action 4】残り7名（特に0–3投稿4名）のヒアリングで低層要因を確定。",
    ]
    if not high:
        lines[1] = lines[1].replace("60+）", "60+）— ヒアリング済み高層データ要確認")
    if low:
        low_names = "、".join(r["生徒名"] for r in low[:4])
        lines.append(f"【補足】低層ヒアリング例: {low_names}…")
    return lines


def build_blocks(rows: list[dict], grad: dict[str, dict], report_date: str) -> list[dict]:
    n_hearing = len(rows)
    n_total = 23
    missing = []
    for name, g in grad.items():
        heard = any(r["生徒名"].replace(" ", "") == name for r in rows)
        if not heard:
            missing.append(f"{g['生徒名']}（{g['卒業時投稿数']}本）")

    # factor aggregation by tier
    tier_factors: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        t = tier(int(row["卒業時投稿数"]))
        for tag in factor_tags(row):
            tier_factors[t][tag] += 1

    blocks: list[dict] = [
        divider(),
        h(2, "4. MGヒアリング — 投稿数要因分析（KFF）"),
        para(f"更新: {report_date} ／ データ: mg_hearing_graduation_posts.tsv ／ ヒアリング {n_hearing}/{n_total}名（中間）"),
        callout(
            "KFF = Key Facts（定量）→ Factors（要因）→ Findings & Framework（示唆・再現可能な伴走）。"
            "報告資料の「所感」「推奨アクション」欄へそのまま転記できる構成。",
            "🧭",
        ),
        h(3, "K — Key Facts（定量）"),
        bullet("23名（中途解約2名除外）／ 平均43.2本・中央値34本"),
        bullet("60投稿達成: 6名（26.1%）／ 100投稿: 2名（8.7%）"),
        bullet(f"ヒアリング収集: {n_hearing}名完了、未収集 {len(missing)}名"),
        h(3, "F — Factors（要因タグ × 投稿数層）"),
        para("各生徒のヒアリングから自動タグ付け。層ごとの出現回数。"),
    ]

    factor_rows = []
    all_tags = sorted({tag for c in tier_factors.values() for tag in c})
    for tag in all_tags:
        factor_rows.append(
            [
                tag,
                str(tier_factors["60+"].get(tag, 0)),
                str(tier_factors["31-59"].get(tag, 0)),
                str(tier_factors["≤30"].get(tag, 0)),
            ]
        )
    if factor_rows:
        blocks.append(table_block(["要因タグ", "60+", "31-59", "≤30"], factor_rows))

    blocks.extend(
        [
            h(3, "F — Framework（MG伴走パターン）"),
            para("ヒアリングに登場したMGサポート手法（出現回数順）。"),
        ]
    )
    for pattern, count, ex in mg_support_patterns(rows)[:12]:
        blocks.append(bullet(f"{pattern}（{count}名）— 例: {ex}"))

    blocks.extend(
        [
            h(3, "生徒別マトリクス（根拠データ）"),
            para("報告資料で個別事例を引用するとき用。"),
        ]
    )

    matrix_rows = []
    for row in sorted(rows, key=lambda r: -int(r["卒業時投稿数"])):
        matrix_rows.append(
            [
                row["生徒名"],
                row["卒業時投稿数"],
                row["区分"],
                (row.get("成功要因（要約）") or "—")[:40],
                (row.get("MG・伴走サポート（要約）") or "—")[:40],
                (row.get("障壁・ペース調整") or "—")[:40],
            ]
        )
    blocks.append(
        table_block(
            ["生徒", "投稿数", "区分", "成功要因", "MGサポート", "障壁"],
            matrix_rows,
        )
    )

    if missing:
        blocks.extend(
            [
                h(3, "未ヒアリング（要追加）"),
                para("、".join(missing)),
            ]
        )

    blocks.extend(
        [
            h(3, "Findings & Actions — コピペ用下書き"),
            para("報告資料のKFF欄へそのまま貼れる文案。"),
        ]
    )
    for line in build_kff_draft(rows, n_total, n_hearing):
        blocks.append(bullet(line))

    # tier summaries as toggles would need children - use headings instead
    for label, lo, hi in [("60+ 高投稿層", 60, 999), ("31-59 中間層", 31, 59), ("≤30 低投稿層", 0, 30)]:
        tier_rows = [r for r in rows if lo <= int(r["卒業時投稿数"]) <= hi]
        if not tier_rows:
            continue
        blocks.append(h(3, f"層別サマリー — {label}（{len(tier_rows)}名）"))
        for row in tier_rows:
            blocks.append(
                bullet(
                    f"{row['担当MG']} — {(row.get('成功要因（要約）') or '')}; "
                    f"伴走: {(row.get('MG・伴走サポート（要約）') or '—')}; "
                    f"障壁: {(row.get('障壁・ペース調整') or '—')}",
                    bold_prefix=f"{row['生徒名']} ({row['卒業時投稿数']}本) ",
                )
            )

    return blocks


def notion_request(method: str, url: str, body: dict | None = None) -> dict:
    key = os.environ.get("NOTION_API_KEY")
    if not key:
        raise SystemExit("NOTION_API_KEY が未設定です")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise SystemExit(f"Notion API error {e.code}: {err}") from e


def append_blocks(page_id: str, blocks: list[dict]) -> None:
    for i in range(0, len(blocks), CHUNK):
        chunk = blocks[i : i + CHUNK]
        notion_request(
            "PATCH",
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            {"children": chunk},
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Post MG hearing KFF to Notion")
    p.add_argument("--page-id", default=DEFAULT_PAGE)
    p.add_argument("--hearing", type=Path, default=DEFAULT_HEARING)
    p.add_argument("--grad", type=Path, default=DEFAULT_GRAD)
    p.add_argument("--date", default="2026-06-04")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    rows = load_hearing(args.hearing)
    grad = load_grad(args.grad)
    blocks = build_blocks(rows, grad, args.date)

    md_path = ROOT / "data/reports/monthly_20260604/mg_hearing_kff.md"
    if not args.dry_run:
        append_blocks(args.page_id, blocks)
        print(f"Posted {len(blocks)} blocks to Notion page {args.page_id}")

    # local mirror for editing
    lines = ["# MGヒアリング KFF（11月卒業・コミット）", "", f"更新: {args.date}", ""]
    for b in blocks:
        t = b.get("type")
        if t and t.startswith("heading"):
            level = t.split("_")[1]
            text = b[t]["rich_text"][0]["text"]["content"]
            lines.append("#" * int(level) + " " + text)
        elif t == "paragraph":
            lines.append(b["paragraph"]["rich_text"][0]["text"]["content"])
            lines.append("")
        elif t == "bulleted_list_item":
            rt_parts = b["bulleted_list_item"]["rich_text"]
            lines.append("- " + "".join(x["text"]["content"] for x in rt_parts))
        elif t == "callout":
            lines.append("> " + b["callout"]["rich_text"][0]["text"]["content"])
            lines.append("")
        elif t == "divider":
            lines.append("---")
            lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
