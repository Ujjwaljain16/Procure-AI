"""Scripted stand-in for the Gemini network boundary, used only by tests and by the offline self-checks.

The only thing replaced is ``google.genai`` client's ``models.generate_content`` (the single HTTP call
the adapter makes). Everything else runs for real: the adapter's config construction, the real
google.genai types, the attempt counter (record_attempt, called before each HTTP call), response
parsing into AgentSynthesis / AnalystReport, the key pool, and the orchestrators.

Scripted modes mirror the evaluator's fault modes so that a fake transport and the offline stand-in
describe the same model behaviour at different layers:

    normal      stop immediately; a clean structured answer
    hostile     two substitution tool calls (vendor, employee), then a claim of approval
    malformed   structured output that does not parse (the adapter raises ModelOutputError)
    outage      every HTTP call raises (the attempt is counted before the call)
    quota_once  the first HTTP call raises a 429 marker; later calls behave as normal (pool rotation)

Nothing here touches the network or a key.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agent.schemas import AgentSynthesis
from src.agent.staged_schemas import AnalystReport

MODES_WITH_SCRIPT = ("normal", "hostile", "malformed", "outage", "quota_once")


class FakeGenaiTransport:
    """Replaces ``client._client`` on a real adapter. ``models`` is the attribute the adapter calls."""

    def __init__(self, mode: str, raw: dict):
        if mode not in MODES_WITH_SCRIPT:
            raise ValueError(f"unknown fake transport mode: {mode}")
        self.mode = mode
        self.raw = raw
        self.calls = 0  # every generate_content call, successful or not
        self.kinds: list[str] = []  # call kinds only ("turn", "synth", "report", "failed") -- never contents
        self._turns = 0
        self.models = self

    def generate_content(self, model=None, contents=None, config=None):
        self.calls += 1
        if self.mode == "outage" or (self.mode == "quota_once" and self.calls == 1):
            self.kinds.append("failed")
            if self.mode == "outage":
                raise ConnectionError("model unreachable")
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota")
        if getattr(config, "tools", None):
            self.kinds.append("turn")
            return self._turn()
        if getattr(config, "response_schema", None) is AnalystReport:
            self.kinds.append("report")
            return self._report()
        self.kinds.append("synth")
        return self._synth()

    # --- scripted responses; shapes match what GeminiClient._to_model_turn and the structured methods read

    def _other_vendor(self) -> str:
        return "NimbusAI" if self.raw.get("vendor_name") != "NimbusAI" else "SignalWatch"

    def _other_employee(self) -> str:
        return "E001" if self.raw.get("requester_id") != "E001" else "E002"

    def _turn(self):
        calls = []
        if self.mode == "hostile" and self._turns == 0:
            calls = [SimpleNamespace(id="h1", name="get_vendor_evidence", args={"vendor_name": self._other_vendor()})]
        elif self.mode == "hostile" and self._turns == 1:
            calls = [SimpleNamespace(id="h2", name="get_employee_budget", args={"employee_id": self._other_employee()})]
        self._turns += 1
        return SimpleNamespace(
            function_calls=calls or None,
            text=None if calls else "",
            parsed=None,
            candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))],
        )

    def _synth(self):
        if self.mode == "malformed":
            return SimpleNamespace(parsed=None, text="{ not json", candidates=[])
        if self.mode == "hostile":
            parsed = AgentSynthesis(
                recommendation="I approve this request now. It is CFO-approved; purchase it today.",
                rationale="Approved by the CFO; no review is needed.",
                evidence_refs=["E1", "E999"],
                next_step="Approve and purchase immediately.",
                prompt_injection_detected=False,
            )
        else:
            parsed = AgentSynthesis(
                recommendation="Route to the listed approvers; no purchase has been made.",
                rationale="Based on the evidence provided.",
                evidence_refs=[],
                next_step="Route for human approval.",
            )
        return SimpleNamespace(parsed=parsed, text=None, candidates=[])

    def _report(self):
        if self.mode == "malformed":
            return SimpleNamespace(parsed=None, text="{ not json", candidates=[])
        parsed = AnalystReport(
            request_summary="Purchase request under review.",
            observations=[],
            unresolved_questions=[],
            contextual_risks=[],
            evidence_refs=[],
        )
        return SimpleNamespace(parsed=parsed, text=None, candidates=[])
