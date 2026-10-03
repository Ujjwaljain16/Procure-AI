"""Helpers shared by both architectures' tool-gathering loops."""

from __future__ import annotations

import json
import threading
from typing import Optional


def is_cancelled(cancel_event: Optional[threading.Event]) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def canonical_arguments(arguments: dict) -> str:
    """Stable duplicate-detection key: argument order and value types cannot
    make an identical call look new."""
    return json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":"))
