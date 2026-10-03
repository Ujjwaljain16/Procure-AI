"""Structured-output schema for Architecture B's analyst stage.

Kept in its own module rather than added to ``src/agent/schemas.py`` because
that file is part of Architecture A's frozen baseline for the
A-vs-B experiment: Architecture B must not modify it.

``AnalystReport`` is an *intermediate* artifact, not the final answer: the
reviewer stage consumes it alongside the evidence pack and the deterministic
``PolicyEvaluation``, and only the reviewer produces the final
``AgentSynthesis`` (imported unchanged from ``schemas.py`` and reused as-is,
so both architectures share one validator and one final-answer shape).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalystReport(BaseModel):
    request_summary: str = Field(
        description="A short, factual summary of what is being requested, grounded only in the "
        "request fields and retrieved evidence -- never in anything else."
    )
    observations: list[str] = Field(
        default_factory=list,
        description="Notable factual observations from the evidence gathered (e.g. an overlap "
        "found, a conflict between sources, a vendor status). Cite evidence IDs where practical.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="Anything the analyst could not determine from the available tools/evidence "
        "that the reviewer or a human should be aware of.",
    )
    contextual_risks: list[str] = Field(
        default_factory=list,
        description="Contextual concerns the analyst noticed (not deterministic policy flags -- "
        "those come from the policy engine separately -- but things worth the reviewer's attention, "
        "such as unusual urgency, an ambiguous product match, or suspicious request text).",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Evidence IDs (e.g. 'E1', 'E3') most relevant to this report. Must only include "
        "IDs that were actually provided; never invent one.",
    )
