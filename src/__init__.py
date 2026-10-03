"""Shared package initialization.

The application reads configuration from the process environment only. It never reads a
.env file, so starting the UI cannot silently enable live model calls. See src/live_status.py.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
