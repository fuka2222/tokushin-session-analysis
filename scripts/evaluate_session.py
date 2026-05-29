#!/usr/bin/env python3
"""1件のZoom文字起こしを評価し、JSONで保存する。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from parse_vtt import load_transcript  # noqa: E402

load_dotenv(ROOT / ".env")

PROMPTS = {
    "structure_1": ROOT / "prompts" / "01_structure_adherence_session1.md",
    "structure_2plus": ROOT / "prompts" / "02_structure_adherence_session2to12.md",
    "hearing": ROOT / "prompts" / "03_hearing_extraction.md",
}


def _fill(template: str, **kwargs: str) -> str:
    out = template
    for key, value in kwargs.items():
        out = out.replace(f"{{{{{key}}}}}", value or "")
    return out


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def call_gemini(prompt: str) -> dict:
    import google.generativeai as genai

    api_key = os.environ.get("GOOGLE_AI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY が未設定です (.env を確認)")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name,
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )
    response = model.generate_content(prompt)
    return _extract_json(response.text)


def build_structure_prompt(
    session_number: int,
    transcript: str,
    student_id: str,
    mg_name: str,
) -> str:
    if session_number == 1:
        path = PROMPTS["structure_1"]
    else:
        path = PROMPTS["structure_2plus"]
    template = path.read_text(encoding="utf-8")
    return _fill(
        template,
        session_number=str(session_number),
        student_id=student_id,
        mg_name=mg_name,
        transcript=transcript,
    )


def build_hearing_prompt(
    session_number: int,
    transcript: str,
    student_id: str,
    sp_start_date: str = "",
    session_date: str = "",
    step_at_assign: str = "",
) -> str:
    template = PROMPTS["hearing"].read_text(encoding="utf-8")
    return _fill(
        template,
        session_number=str(session_number),
        student_id=student_id,
        transcript=transcript,
        sp_start_date=sp_start_date,
        session_date=session_date,
        step_at_assign=step_at_assign,
    )


def evaluate(
    transcript_path: Path,
    session_number: int,
    student_id: str,
    mg_name: str,
    sp_start_date: str = "",
    session_date: str = "",
    step_at_assign: str = "",
    skip_hearing: bool = False,
) -> dict:
    transcript = load_transcript(transcript_path)
    structure_prompt = build_structure_prompt(
        session_number, transcript, student_id, mg_name
    )
    structure = call_gemini(structure_prompt)

    hearing = None
    if not skip_hearing:
        hearing_prompt = build_hearing_prompt(
            session_number,
            transcript,
            student_id,
            sp_start_date,
            session_date,
            step_at_assign,
        )
        hearing = call_gemini(hearing_prompt)

    return {
        "structure": structure,
        "hearing": hearing,
        "meta": {
            "transcript_path": str(transcript_path),
            "transcript_chars": len(transcript),
            "evaluated_at": datetime.utcnow().isoformat() + "Z",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="伴走セッション1件を評価")
    parser.add_argument("--vtt", required=True, type=Path, help="VTTまたはtxt")
    parser.add_argument("--session", required=True, type=int, help="セッション番号 1-12")
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--mg-name", required=True)
    parser.add_argument("--sp-start-date", default="")
    parser.add_argument("--session-date", default="")
    parser.add_argument("--step-at-assign", default="")
    parser.add_argument("--skip-hearing", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力JSON（省略時は data/results/{student_id}_{session}.json）",
    )
    args = parser.parse_args()

    out = args.output or (
        ROOT / "data" / "results" / f"{args.student_id}_{args.session}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    result = evaluate(
        args.vtt,
        args.session,
        args.student_id,
        args.mg_name,
        args.sp_start_date,
        args.session_date,
        args.step_at_assign,
        args.skip_hearing,
    )
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rate = result["structure"].get("structure_adherence_rate")
    print(f"保存: {out}")
    print(f"構成遵守率: {rate}")
    print(f"欠落ブロック: {result['structure'].get('missing_blocks', [])}")


if __name__ == "__main__":
    main()
