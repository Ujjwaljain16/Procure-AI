"""Mandatory evidence preflight.

The policy engine's inputs (employee budget, catalog overlap, purchase history,
vendor registry and vendor-risk state) are gathered here, in code, from the
validated request. The model never chooses these calls and never supplies
their arguments, so no model behavior -- a hostile argument, a skipped
catalog, a failed call -- can change what the policy engine sees.

Each call is made with ``mandatory=True``: its result becomes an authoritative
policy input, and a failure is recorded as "unavailable" (never as a favorable
value), because the registry's accessors then report the input as absent.
"""

from __future__ import annotations

from src.agent.tools_registry import ToolRegistry


def gather_mandatory_evidence(raw: dict, registry: ToolRegistry | None = None) -> ToolRegistry:
    registry = registry if registry is not None else ToolRegistry()

    requester_id = raw.get("requester_id")
    if requester_id:
        registry.execute("get_employee_budget", {"employee_id": requester_id}, mandatory=True)

    catalog_args = {
        key: raw[field]
        for key, field in (("product_name", "product_name"), ("vendor_name", "vendor_name"), ("category", "category"))
        if raw.get(field)
    }
    if catalog_args:
        registry.execute("search_catalog", catalog_args, mandatory=True)

    history_args = {
        key: raw[field] for key, field in (("product_name", "product_name"), ("vendor_name", "vendor_name")) if raw.get(field)
    }
    if history_args:
        registry.execute("search_purchase_history", history_args, mandatory=True)

    vendor_name = raw.get("vendor_name")
    if vendor_name:
        registry.execute("get_vendor_evidence", {"vendor_name": vendor_name}, mandatory=True)

    return registry
