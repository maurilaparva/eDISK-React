"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: image_analyzer.py
@Time: 11/14/25; 11:32 AM
"""
from __future__ import annotations

import json
import re
from typing import Iterable, List, Sequence, Tuple

from django.conf import settings

from . import openai_client

_PROMPT_TEMPLATE = (
    "You analyse photographs of dietary supplement packaging. "
    "Identify any product or ingredient names that are clearly visible. "
    "Respond ONLY with valid JSON using this schema: "
    '{"supplements": ["name", ...], "confidence": "high|medium|low"}. '
    "Return an empty list when nothing can be identified."
)


def detect_supplement_names(image_bytes: bytes) -> List[str]:
    """Return the supplement names detected in ``image_bytes``."""

    if not image_bytes:
        return []

    raw_response = openai_client.vision_describe(
        image_bytes,
        prompt=_PROMPT_TEMPLATE,
        model=getattr(settings, "OPENAI_VISION_MODEL", None),
    )

    return _extract_names(raw_response)


def augment_query_with_detections(
        user_query: str,
        detected_names: Sequence[str],
) -> Tuple[str, List[str]]:
    """Merge detected names into ``user_query`` and return the new query."""

    query = (user_query or "").strip()
    clean_names = _normalise_names(detected_names)

    if not clean_names:
        return query, []

    if query:
        remaining = [n for n in clean_names if n.lower() not in query.lower()]
        if not remaining:
            return query, clean_names
        addition = ", ".join(remaining)
        augmented = f"{query}\nThe attached image shows: {addition}."
        return augmented, clean_names

    augmented = f"Please tell me about {clean_names[0]}."
    return augmented, clean_names


def _extract_names(response_text: str) -> List[str]:
    if not response_text:
        return []

    response_text = response_text.strip()
    parsed = _try_parse_json(response_text)

    if not parsed:
        # Attempt to recover JSON substring from free-form text
        match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
        if match:
            parsed = _try_parse_json(match.group(0))

    if isinstance(parsed, dict):
        candidates = parsed.get("supplements") or parsed.get("names")
        return _normalise_names(candidates)

    # Fallback: look for patterns such as "Supplement: Fish Oil"
    match = re.search(r"(?i)supplement(?:\s+name)?\s*[:\-]\s*([A-Za-z0-9\s-]{3,})", response_text)
    if match:
        return _normalise_names([match.group(1)])

    return []


def _try_parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _normalise_names(values: Iterable[str] | None) -> List[str]:
    names: List[str] = []
    if not values:
        return names

    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        names.append(text)

    # Preserve order while deduplicating (case-insensitive)
    seen = set()
    unique: List[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)

    return unique
