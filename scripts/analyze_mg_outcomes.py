#!/usr/bin/env python3
"""
MGの構成遵守度（スクリプト伝達の確率が高い群）と、担当生徒の成果を比較する。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def load_evaluation_results(results_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(results_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        structure = data.get("structure") or {}
        meta = data.get("meta") or {}
        stem = path.stem
        parts = stem.rsplit("_", 1)
        student_id = parts[0] if len(parts) == 2 else stem
        session_number = structure.get("session_number")
        if session_number is None and len(parts) == 2:
            try:
                session_number = int(parts[1])
            except ValueError:
                session_number = None

        rows.append(
            {
                "student_id": structure.get("student_id") or student_id,
                "session_number": session_number,
                "mg_name": structure.get("mg_name"),
                "structure_adherence_rate": structure.get("structure_adherence_rate"),
                "script_delivery_likelihood": structure.get(
                    "script_delivery_likelihood"
                ),
                "missing_blocks": ",".join(structure.get("missing_blocks") or []),
                "result_file": path.name,
            }
        )
    return pd.DataFrame(rows)


def mg_adherence_summary(eval_df: pd.DataFrame, session_filter: int = 1) -> pd.DataFrame:
    sub = eval_df[eval_df["session_number"] == session_filter].copy()
    if sub.empty:
        return pd.DataFrame()
    return (
        sub.groupby("mg_name", dropna=False)
        .agg(
            sessions=("structure_adherence_rate", "count"),
            adherence_mean=("structure_adherence_rate", "mean"),
            adherence_median=("structure_adherence_rate", "median"),
            high_likelihood_share=(
                "script_delivery_likelihood",
                lambda s: (s == "high").mean(),
            ),
        )
        .reset_index()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "data" / "results",
    )
    parser.add_argument(
        "--outcomes",
        type=Path,
        default=ROOT / "data" / "outcomes" / "student_outcomes.csv",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ROOT / "data" / "metadata" / "sessions.csv",
    )
    parser.add_argument(
        "--mg-threshold",
        type=float,
        default=0.85,
        help="MGを「型伝達が高い」とみなす初回遵守率の中央値閾値",
    )
    parser.add_argument(
        "--session-for-mg",
        type=int,
        default=1,
        help="MG判定に使うセッション番号（通常1回目）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "results" / "mg_adherence_vs_outcomes.csv",
    )
    args = parser.parse_args()

    eval_df = load_evaluation_results(args.results_dir)
    if eval_df.empty:
        print("評価結果JSONがありません。先に batch_evaluate を実行してください。")
        return

    mg_summary = mg_adherence_summary(eval_df, args.session_for_mg)
    if mg_summary.empty:
        print("MGサマリを作成できませんでした。")
        return

    mg_summary["high_adherence_mg"] = (
        mg_summary["adherence_median"] >= args.mg_threshold
    )

    if not args.outcomes.exists():
        print(f"成果CSVがありません: {args.outcomes}")
        print("\n--- MG別 構成遵守（初回）---")
        print(mg_summary.to_string(index=False))
        mg_summary.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\n保存: {args.output}")
        return

    outcomes = pd.read_csv(args.outcomes)
    # student_id で結合。outcomes に mg_name が無ければ sessions.csv から補完
    if "mg_name" not in outcomes.columns and args.metadata.exists():
        sessions = pd.read_csv(args.metadata)
        mg_map = (
            sessions.sort_values("session_number")
            .groupby("student_id")["mg_name"]
            .first()
        )
        outcomes = outcomes.copy()
        outcomes["mg_name"] = outcomes["student_id"].map(mg_map)

    if "mg_name" not in outcomes.columns:
        print("outcomes または sessions.csv に mg_name が必要です。")
        return

    student_mg = outcomes[["student_id", "mg_name"]].drop_duplicates()
    student_mg = student_mg.merge(
        mg_summary[["mg_name", "high_adherence_mg", "adherence_median"]],
        on="mg_name",
        how="left",
    )
    merged = outcomes.merge(student_mg, on=["student_id", "mg_name"], how="left")

    numeric_cols = [
        c
        for c in merged.columns
        if c
        not in {
            "student_id",
            "mg_name",
            "high_adherence_mg",
            "adherence_median",
        }
        and pd.api.types.is_numeric_dtype(merged[c])
    ]

    print("\n=== MG別 初回構成遵守 ===")
    print(mg_summary.to_string(index=False))

    if numeric_cols:
        print("\n=== 高遵守MG vs それ以外（生徒単位成果の平均）===")
        for col in numeric_cols:
            grp = merged.groupby("high_adherence_mg")[col].mean()
            print(f"{col}:")
            print(f"  高遵守MG担当: {grp.get(True, float('nan')):.2f}")
            print(f"  その他:       {grp.get(False, float('nan')):.2f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\n結合CSV保存: {args.output}")


if __name__ == "__main__":
    main()
