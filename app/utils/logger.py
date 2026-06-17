from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


_LOGGERS: dict[str, logging.Logger] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_log_file_path() -> Path:
    return _project_root() / "logs" / "app.log"


def truncate_text(value: Any, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def summarize_sequence(items: Any, sample_key: str = "title", sample_size: int = 3) -> Dict[str, Any]:
    sequence = list(items or [])
    sample = []
    for item in sequence[:sample_size]:
        if isinstance(item, dict):
            sample.append(item.get(sample_key) or item.get("name") or item.get("id"))
        else:
            sample.append(truncate_text(item, 40))
    return {
        "count": len(sequence),
        "sample": sample,
    }


def summarize_graph_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    state = state or {}
    return {
        "user_id": state.get("user_id"),
        "project_id": state.get("project_id"),
        "current_phase": state.get("current_phase"),
        "next_step": state.get("next_step"),
        "needs_human_approval": state.get("needs_human_approval"),
        "approval_response": state.get("approval_response"),
        "messages_count": len(state.get("messages") or []),
        "tasks_count": len(state.get("tasks") or []),
        "risks_count": len(state.get("risks") or []),
        "project_data_keys": sorted(list((state.get("project_data") or {}).keys()))[:10],
    }


def get_logger(name: str) -> logging.Logger:
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(os.getenv("APP_LOG_LEVEL", "INFO").upper())
    logger.propagate = False

    if not logger.handlers:
        formatter = logging.Formatter("%(message)s")

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        if os.getenv("APP_LOG_TO_FILE", "true").lower() == "true":
            log_dir = _project_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    _LOGGERS[name] = logger
    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    level: str = "info",
    **fields: Any,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    message = json.dumps(record, ensure_ascii=False, default=str)
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message)


def read_recent_log_events(limit: int = 50, event_prefix: Optional[str] = None) -> list[Dict[str, Any]]:
    log_file = get_log_file_path()
    if not log_file.exists():
        return []

    events: list[Dict[str, Any]] = []
    try:
        with log_file.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()

        for line in reversed(lines):
            if len(events) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_prefix and not str(payload.get("event", "")).startswith(event_prefix):
                continue
            events.append(payload)
    except Exception:
        return []

    return list(reversed(events))