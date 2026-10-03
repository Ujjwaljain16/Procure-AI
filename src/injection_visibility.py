"""Deterministic visibility of injected instructions in business text.

Policy section 9 says that if business data tries to change the copilot's rules, bypass
controls, fabricate approval, or tell the model to ignore policy, the copilot should
ignore the instruction and "optionally surface prompt_injection_detected". The public
evaluation expects the flag on the incomplete-request injection case (PUB-05), so the flag
cannot depend only on whether the model happens to notice the injection.

This module is a visibility signal and nothing else. It is a fixed, narrow set of
instruction-shaped patterns. It reads free text only: the request's business_justification
and the findings of retrieved evidence. It never changes approvals, missing information,
risk flags other than prompt_injection_detected, or human review. It is not a safety control:
the structural boundary (no path that approves, purchases, or edits budgets) is what protects
the user. A pattern miss means the flag is not raised, not that the text is safe.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

FLAG = "prompt_injection_detected"

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("ignore_rules", re.compile(r"\bignore\b[^.;]{0,40}\b(rules|instructions|policy|policies|controls|guidelines|procurement)\b", re.IGNORECASE)),
    ("treat_as_approved", re.compile(r"\b(treat|consider|regard)\b[^.;]{0,30}\bas\b[^.;]{0,20}\b(approved|authori[sz]ed|signed[ -]off|cfo[ -]approved)\b", re.IGNORECASE)),
    ("approve_now", re.compile(r"\bapprove\b[^.;]{0,20}\b(immediately|right away|right now|without review|without delay)\b", re.IGNORECASE)),
    ("bypass_control", re.compile(r"\b(skip|bypass|override)\b[^.;]{0,30}\b(security|privacy|legal|review|controls?|approvals?)\b", re.IGNORECASE)),
    ("do_not_route", re.compile(r"\bdo not (route|escalate)\b", re.IGNORECASE)),
    ("change_threshold", re.compile(r"\bchange (?:the )?(?:approval )?threshold\b", re.IGNORECASE)),
    ("prompt_reference", re.compile(r"\b(system|developer) (?:prompt|message|instructions?)\b", re.IGNORECASE)),
)


def matched_patterns(text: Optional[str]) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(name for name, pattern in _PATTERNS if pattern.search(text))


def injection_visible(texts: Iterable[Optional[str]]) -> bool:
    """True when any supplied business text carries an instruction-shaped pattern."""
    return any(matched_patterns(text) for text in texts)
