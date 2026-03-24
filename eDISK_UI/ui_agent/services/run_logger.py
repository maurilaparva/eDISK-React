"""
_*_CODING:UTF-8_*_
@Author: Yu Hou
@File: run_logger.py.py
@Time: 11/4/25; 6:01 PM
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pprint import pformat
from typing import Any, Dict

from django.conf import settings


def _ensure_log_dir() -> str:
    directory = getattr(settings, "QUERY_LOG_DIR", None)
    if not directory:
        # Fallback to a logs folder inside the app if the setting is absent.
        base_dir = os.path.join(settings.BASE_DIR, "ui_agent", "logs")
        directory = base_dir
    os.makedirs(directory, exist_ok=True)
    return directory


def _sanitize_filename(value: str) -> str:
    """Return a filesystem-safe slug for the provided value."""

    if not value:
        return "run"
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^a-zA-Z0-9_\-]", "", value)
    return value or "run"


def _write_section(handle, title: str, content: Any) -> None:
    handle.write(f"{title}\n")
    handle.write(f"{'-' * len(title)}\n")
    if isinstance(content, str):
        handle.write(content.strip() + "\n\n")
    else:
        handle.write(pformat(content, width=100, compact=False) + "\n\n")


def log_pipeline_run(run_id: str, details: Dict[str, Any]) -> str:
    """
    Persist a structured log for a single pipeline execution.

    Returns the absolute path to the written log file for observability.
    """

    directory = _ensure_log_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{_sanitize_filename(run_id)}.txt"
    path = os.path.join(directory, filename)

    header = {
        "timestamp_utc": timestamp,
        "question": details.get("question"),
        "relation": details.get("relation"),
    }

    with open(path, "w", encoding="utf-8") as handle:
        _write_section(handle, "Query Metadata", header)
        _write_section(handle, "Parsed Entities", details.get("parsed_entities"))
        _write_section(handle, "Entity Linking", details.get("entity_linking"))
        _write_section(handle, "Direct Relationship Query", details.get("direct_query"))
        _write_section(handle, "Direct Relationship Result", details.get("direct_result"))
        _write_section(handle, "Context Queries & Results", details.get("context"))
        _write_section(handle, "Link Prediction", details.get("link_prediction"))
        _write_section(handle, "Verification", details.get("verification"))

    return path