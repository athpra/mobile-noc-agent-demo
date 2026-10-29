"""
propose_cm_change: the only path that changes the network.

Flow: parse and check the change (guardrails) -> build a diff -> pause the
graph with interrupt() until a person approves or rejects -> apply.

LangGraph re-runs this function from the top when the graph resumes, so
nothing before interrupt() may have side effects.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from src.context import DemoContext
from src.network.oss import UnknownCellError
from src.tools.guardrails import GuardrailError, check_change, checks_as_dicts, config_diff, parse_value


def build_change_tools(ctx: DemoContext) -> list[BaseTool]:
    oss = ctx.oss

    @tool
    def propose_cm_change(cell_id: str, attribute: str, new_value: str, reason: str) -> str:
        """Propose ONE configuration change on one cell, e.g. attribute="nRPCI".
        Allowed attributes: nRPCI, a3OffsetDb, hysteresisDb, timeToTriggerMs,
        cellIndividualOffsetDb. The change is checked, shown to an engineer as a
        diff, and applied only if they approve. `reason` should state the evidence."""
        try:
            cid = oss.resolve_cell(cell_id)
            value = parse_value(attribute, new_value)
        except (UnknownCellError, GuardrailError) as exc:
            return f"Blocked by guardrails: {exc}"

        checks = check_change(oss, cid, attribute, value, ctx.changes_applied)
        failed = [c for c in checks if c.status == "fail"]
        if failed:
            return "Blocked by guardrails, not sent for approval: " + "; ".join(
                f"{c.name}: {c.detail}" for c in failed
            )

        current = oss.net.config_at(cid, oss.now).get(attribute)
        decision = interrupt({
            "kind": "cm_change",
            "cell_id": cid,
            "managed_object": oss.get_cell(cid)["managed_object"],
            "attribute": attribute,
            "current_value": current,
            "proposed_value": value,
            "reason": reason,
            "checks": checks_as_dicts(checks),
            "diff": config_diff(oss, cid, attribute, value),
            "network_time": ctx.network_time,
        })

        approver = (decision or {}).get("approver") or "operator"
        comment = (decision or {}).get("comment", "")
        if not (decision or {}).get("approved"):
            ctx.audit.log("cm_change", ctx.network_time, cell_id=cid, attribute=attribute,
                          old=current, new=value, decision="rejected", approver=approver, comment=comment)
            return (f"The engineer REJECTED the change ({attribute} {current} -> {value} on {cid})."
                    f"{' Comment: ' + comment if comment else ''} Nothing was applied. Do not resubmit the "
                    f"same change; explain your evidence or propose an alternative.")

        applied = oss.patch_cell(cid, attribute, value, source=f"noc-agent, approved by {approver}")
        ctx.changes_applied += 1
        ctx.audit.log("cm_change", ctx.network_time, cell_id=cid, attribute=attribute,
                      old=current, new=value, decision="approved", approver=approver, comment=comment)
        oss.advance(15)  # let one new ROP complete so the effect can be verified
        return (f"APPLIED at {applied['time']}: {cid} {attribute} {current} -> {value} (approved by {approver}). "
                f"Network time is now {ctx.network_time}, so the {applied['time']} ROP is complete. "
                f"Verify with get_kpis before closing.")

    return [propose_cm_change]
