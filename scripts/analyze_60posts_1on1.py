#!/usr/bin/env python3
"""60投稿以上の生徒と講師1on1利用の突合"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

SESSION_COLS = ["1回目", "2回目", "3回目", "4回目", "5回目"]

SURNAME_MAP = {
    "くまもと": "熊本",
    "はなだ": "花田",
    "きくち": "菊池",
    "みやけ": "三宅",
    "うちだ": "内田",
    "ごとう": "後藤",
    "たわら": "俵",
    "らぶ": "ラブ",
    "さかもと": "坂本",
    "なかお": "中尾",
    "ありやま": "有山",
    "おおにし": "大西",
    "しもたか": "下高谷",
    "わたなべ": "渡",
    "ふかくさ": "深草",
    "おばた": "小幡",
    "いけぐち": "池口",
    "こもり": "小森",
    "しらどう": "白道",
    "かしはら": "柏原",
    "よつい": "四井",
    "ただ": "多田",
    "たかばた": "高畑",
    "おおすが": "大菅",
    "さいとう": "斉藤",
    "やました": "山本",
    "にしむら": "西村",
    "こばやし": "小林",
    "ながい": "永井",
    "みやざと": "宮里",
    "こせき": "小関",
    "しが": "志賀",
    "ねもと": "根元",
    "まつい": "松井",
    "すがの": "菅野",
    "ふじため": "藤田",
    "えのきだ": "榎田",
    "たなか": "田中",
    "やまだ": "山田",
    "なかつか": "中塚",
    "すがわら": "菅原",
    "すぎた": "杉田",
    "おおしろ": "大城",
    "つるた": "鶴田",
    "にしじま": "西島",
}


def norm(s) -> str:
    if pd.isna(s):
        return ""
    return str(s).replace(" ", "").replace("　", "").strip().lower()


def is_used(v) -> bool:
    if v is True:
        return True
    if isinstance(v, (int, float)) and pd.notna(v) and v >= 1:
        return True
    return str(v).upper() in ("TRUE", "1", "1.0")


def parse_posts(v) -> float:
    import numpy as np

    if pd.isna(v) or str(v).strip() in ("", "ー", "-", "nan"):
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def mg_match(a, b) -> bool:
    na, nb = norm(a), norm(b)
    return bool(na and nb and (na == nb or na in nb or nb in na))


def load_kanji_map(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", dtype=str)
    df["nn"] = df["生徒"].apply(norm)
    df["kanji_norm"] = df["漢字名"].apply(norm)
    df["投稿数"] = pd.to_numeric(df["投稿数"], errors="coerce")
    return df


def load_60plus(path: Path) -> pd.DataFrame:
    import numpy as np

    raw = pd.read_excel(path, sheet_name="新 月次投稿数", header=None)
    rows = []
    for i in range(11, len(raw)):
        name = raw.iloc[i, 4]
        gp = parse_posts(raw.iloc[i, 13])
        if pd.isna(name) or np.isnan(gp) or gp < 60:
            continue
        rows.append(
            {
                "name": str(name).strip(),
                "nn": norm(name),
                "posts": int(gp),
                "mg": str(raw.iloc[i, 6]).strip() if pd.notna(raw.iloc[i, 6]) else "",
            }
        )
    return pd.DataFrame(rows)


def load_1on1_from_tsv(path: Path) -> pd.DataFrame:
    one = pd.read_csv(path, sep="\t", dtype=str)
    one = one[one["To"].notna() & (one["To"].str.strip() != "")]
    one = one.drop_duplicates(subset=["To"], keep="last")
    for c in SESSION_COLS:
        one[c] = one[c].apply(is_used)
    one["sessions"] = one.apply(lambda r: sum(1 for c in SESSION_COLS if r[c]), axis=1)
    one["any_1on1"] = one["sessions"] > 0
    return one


def load_1on1(path: Path, tsv: Path | None = None) -> pd.DataFrame:
    if tsv and tsv.exists():
        return load_1on1_from_tsv(tsv)
    one = pd.read_excel(path, sheet_name="コミット生徒の契約日・講師1on1実施チェック", header=0)
    one["sessions"] = one.apply(lambda r: sum(1 for c in SESSION_COLS if is_used(r[c])), axis=1)
    one["any_1on1"] = one["sessions"] > 0
    return one


def load_uid_map(path: Path) -> dict[str, str]:
    raw = pd.read_excel(path, sheet_name="セッション実施状況管理", header=None)
    uid_map: dict[str, str] = {}
    for i in range(10, len(raw)):
        n, u = raw.iloc[i, 7], raw.iloc[i, 8]
        if pd.notna(n) and pd.notna(u):
            uid_map[norm(n)] = str(u).strip().lower()
    return uid_map


def match_by_kanji(kanji: str, one: pd.DataFrame):
    kn = norm(kanji)
    if not kn:
        return None, None
    hits = one[one["To"].apply(norm) == kn]
    if len(hits) == 1:
        return hits.iloc[0], "kanji_map"
    hits = one[one["To"].astype(str).str.replace(" ", "").str.replace("　", "").apply(norm) == kn]
    if len(hits) == 1:
        return hits.iloc[0], "kanji_map"
    return None, None


def match_one(g: dict, one: pd.DataFrame, uid_map: dict[str, str], kanji: str | None = None):
    if kanji:
        o, how = match_by_kanji(kanji, one)
        if o is not None:
            return o, how

    hits = one[one["To"].apply(norm) == g["nn"]]
    if len(hits) == 1:
        return hits.iloc[0], "exact"

    uid = uid_map.get(g["nn"], "")
    if uid:
        for _, o in one.iterrows():
            em = str(o.get("生徒のメールアドレス", "")).lower()
            if uid and uid in em.replace("@", ""):
                return o, "email"

    for key, sur in SURNAME_MAP.items():
        if not g["nn"].startswith(key):
            continue
        h = one[one["To"].astype(str).str.startswith(sur)]
        if g["mg"]:
            h = h[h["担当MG"].apply(lambda x: mg_match(x, g["mg"]))]
        if len(h) == 1:
            return h.iloc[0], f"surname:{sur}"
    return None, None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit-plan",
        type=Path,
        default=Path.home() / "Downloads" / "コミットプラン (8).xlsx",
    )
    parser.add_argument(
        "--kanji-map",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "metadata" / "nov_graduate_kanji_map.tsv",
    )
    parser.add_argument(
        "--1on1-tsv",
        dest="oneon1_tsv",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "metadata" / "instructor_1on1_latest.tsv",
        help="講師1on1最新TSV（貼付 or エクスポート）。あればExcelより優先",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "reports"
        / "monthly_20260604"
        / "commit_60posts_1on1.csv",
    )
    parser.add_argument(
        "--nov-out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "reports"
        / "monthly_20260604"
        / "nov_graduates_1on1_hearing.csv",
    )
    args = parser.parse_args()

    g60 = load_60plus(args.commit_plan)
    one = load_1on1(args.commit_plan, tsv=args.oneon1_tsv)
    uid_map = load_uid_map(args.commit_plan)
    kanji_df = load_kanji_map(args.kanji_map) if args.kanji_map.exists() else pd.DataFrame()
    kanji_by_nn = kanji_df.set_index("nn").to_dict("index") if len(kanji_df) else {}

    rows = []
    for g in g60.to_dict("records"):
        km = kanji_by_nn.get(g["nn"], {})
        kanji = km.get("漢字名") if km else None
        o, how = match_one(g, one, uid_map, kanji=kanji)
        rows.append(
            {
                **g,
                "kanji_from_map": kanji or "",
                "match_method": how,
                "to_kanji": o["To"] if o is not None else (kanji or ""),
                "sessions_1on1": int(o["sessions"]) if o is not None else None,
                "any_1on1": bool(o["sessions"] > 0) if o is not None else None,
                "instructor": str(o.get("講師名", "") or "") if o is not None else "",
                "mg_1on1": str(o.get("担当MG", "") or "") if o is not None else "",
                **{f"used_{c}": is_used(o[c]) if o is not None else None for c in SESSION_COLS},
            }
        )

    out_df = pd.DataFrame(rows).sort_values("posts", ascending=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")

    matched = out_df[out_df["match_method"].notna()]
    print(f"60+ students: {len(out_df)}")
    print(f"Matched: {len(matched)}")
    if len(matched):
        print(f"1on1 used: {matched['any_1on1'].sum()} ({matched['any_1on1'].mean()*100:.1f}%)")
        print(f"Avg sessions: {matched['sessions_1on1'].mean():.2f}")

    # Nov cohort with hearing + 1on1
    if len(kanji_df):
        nov_rows = []
        for _, r in kanji_df.iterrows():
            o, how = match_by_kanji(r["漢字名"], one)
            if o is None:
                o, how = match_one({"nn": r["nn"], "mg": ""}, one, uid_map, kanji=r["漢字名"])
            flags = {}
            for c in SESSION_COLS:
                if o is None:
                    flags[c] = ""
                else:
                    flags[c] = "●" if is_used(o[c]) else "○"
            nov_rows.append(
                {
                    "生徒": r["生徒"],
                    "漢字名": r["漢字名"],
                    "投稿数": int(r["投稿数"]) if pd.notna(r["投稿数"]) else None,
                    "区分": r["区分"],
                    "1on1回数": int(o["sessions"]) if o is not None else None,
                    "1on1利用": "あり" if o is not None and o["sessions"] > 0 else ("なし" if o is not None else "未確認"),
                    "講師名": str(o.get("講師名", "") or "") if o is not None else "",
                    "担当MG": str(o.get("担当MG", "") or "") if o is not None else "",
                    **flags,
                    "成功要因": r.get("成功要因", ""),
                    "MGサポート": r.get("MGサポート", ""),
                    "障壁": r.get("障壁", ""),
                }
            )
        nov_out = pd.DataFrame(nov_rows)
        nov_out.to_csv(args.nov_out, index=False, encoding="utf-8-sig")
        g60_nov = nov_out[nov_out["投稿数"] >= 60]
        print(f"\n=== 11月入会コホート ({len(nov_out)}名) ===")
        for _, row in nov_out.iterrows():
            flag_str = "".join(row.get(c, "—") or "—" for c in SESSION_COLS)
            n1 = row["1on1回数"]
            n1s = f"{int(n1)}回" if pd.notna(n1) else "—"
            print(
                f"  {row['生徒']:18s} {row['漢字名']:14s} {row['投稿数']:3}本 "
                f"1on1:{n1s:4s} [{flag_str}] {row['区分']}"
            )
        if len(g60_nov):
            used = (g60_nov["1on1利用"] == "あり").sum()
            print(f"\n60投稿以上 {len(g60_nov)}名 → 1on1利用 {used}名 / 未利用 {(g60_nov['1on1利用']=='なし').sum()}名")

    print(f"CSV: {args.out}")
    if args.kanji_map.exists():
        print(f"Nov CSV: {args.nov_out}")


if __name__ == "__main__":
    main()
