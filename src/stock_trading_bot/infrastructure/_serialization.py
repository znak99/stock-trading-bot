"""Internal deterministic serialization helpers for infrastructure artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def to_serializable(value: Any) -> Any:
    """Convert runtime values into deterministic JSON-friendly structures."""

    if is_dataclass(value):
        return {key: to_serializable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_serializable(item) for item in value]
    return value


def dump_json(path: Path, payload: Any) -> None:
    """Write a deterministic JSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        to_serializable(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    path.write_text(f"{serialized}\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    """Append a deterministic JSONL record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        to_serializable(payload),
        ensure_ascii=False,
        sort_keys=True,
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{serialized}\n")
