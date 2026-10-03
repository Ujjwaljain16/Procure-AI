"""User-facing failure taxonomy.

Maps a raw technical failure reason -- an exception class name from the
model SDK, or a symbolic token this codebase controls -- to a small,
user-facing category and message. Lives in its own module (not in
src/ui/view_model.py) so the shared final validator can use it without a
circular import; the raw reason is never discarded by callers, it keeps
flowing through gemini_unavailable_reason, logs, and stored evaluation
results unchanged.
"""

from __future__ import annotations

_FAILURE_CATEGORY_MESSAGES = {
    "MODEL_UNAVAILABLE": "Automated analysis is temporarily unavailable.",
    "MODEL_OUTPUT_INVALID": "Automated analysis returned a response that could not be used.",
    "TOOL_UNAVAILABLE": "A required data source is temporarily unavailable.",
    "REQUEST_INVALID": "This request could not be processed.",
    "POLICY_EVALUATION_FAILED": "Policy evaluation could not be completed.",
    "ANALYSIS_TIMEOUT": "Analysis timed out.",
}

_KNOWN_FAILURE_REASONS = {
    "GeminiConfigurationError": "MODEL_UNAVAILABLE",
    "EMPTY_RESPONSE": "MODEL_OUTPUT_INVALID",
    "PARSE_FAILED": "MODEL_OUTPUT_INVALID",
    # Identity entries so a caller that already knows the category can go
    # through the same function and get the same vetted message, instead of
    # a second hardcoded copy of the text.
    **{name: name for name in _FAILURE_CATEGORY_MESSAGES},
}


def classify_failure_reason(raw_reason: str) -> tuple[str, str]:
    """Maps a raw technical failure reason to (category, user-facing message).

    Anything not recognized defaults to MODEL_UNAVAILABLE -- the safest
    reading for a reason that reached here through gemini_unavailable_reason.
    """
    category = _KNOWN_FAILURE_REASONS.get(raw_reason, "MODEL_UNAVAILABLE")
    return category, _FAILURE_CATEGORY_MESSAGES[category]
