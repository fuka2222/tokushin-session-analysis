"""VTTファイルを評価用テキストに正規化する。"""
from __future__ import annotations

import re
from pathlib import Path

try:
    import webvtt
except ImportError:
    webvtt = None


def parse_vtt_regex(vtt_content: str) -> str:
    lines = vtt_content.split("\n")
    text_lines: list[str] = []
    timecode_pattern = re.compile(
        r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}"
    )

    for line in lines:
        line = line.strip()
        if not line or timecode_pattern.match(line) or line.startswith("WEBVTT"):
            continue
        if line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line)
        if line:
            text_lines.append(line)

    seen: set[str] = set()
    unique: list[str] = []
    for line in text_lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)

    normalized = "\n".join(unique)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def parse_vtt_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    if webvtt is None:
        return parse_vtt_regex(content)

    try:
        from io import StringIO

        vtt = webvtt.read_buffer(StringIO(content))
        lines: list[str] = []
        for caption in vtt:
            text = re.sub(r"<[^>]+>", "", caption.text.strip())
            text = re.sub(r"\s+", " ", text)
            if text:
                lines.append(text)
        seen: set[str] = set()
        unique = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        return "\n".join(unique).strip()
    except Exception:
        return parse_vtt_regex(content)


def load_transcript(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return parse_vtt_file(path)
    return path.read_text(encoding="utf-8", errors="replace").strip()
