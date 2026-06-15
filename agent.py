"""
agent.py — Multi-Agent Reasoning Engine
========================================
Owns:
  - Agent persona system prompts (PROMPTS)
  - Dry-run rule-based fallback evaluation logic
  - execute_reasoning() public interface consumed by main.py and batch_manager.py

Does NOT own:
  - Which LLM is called (delegated to llm_provider.get_provider())
  - HTTP transport, retries, auth, or JSON cleaning (all in llm_provider.py)

To swap the LLM backend, set the LLM_PROVIDER environment variable.
No code changes required anywhere in this file.
"""

import datetime
import json
import logging
import os
import re
from typing import Any

from llm_provider import get_provider, LLMProvider

logger = logging.getLogger("adp-agent.engine")


# ---------------------------------------------------------------------------
# Agent persona system prompts
# ---------------------------------------------------------------------------

PROMPTS = {
    "onboarding": """
You are the ADP Model Context Protocol Onboarding Agent. Your primary job is to review a candidate's file data block and confirm if it is structurally ready to be hired into downstream payroll and SCIM core tables.

You must review the file for three mandatory field criteria:
1. startDate (Must be a valid YYYY-MM-DD format string, and must not be null/empty)
2. email (Must be a valid email format)
3. department (Must be provided and active)

When analyzing the payload input, return a strict JSON block using this schema structure:
{
  "status": "complete" | "incomplete",
  "missing_fields": ["field_name1", "field_name2"],
  "validation_summary": "Explanation of what is complete or what needs correction",
  "remediation_draft": "If incomplete, draft a polite, highly professional template email from the manager asking the candidate to supply the missing information. If complete, output an empty string."
}

Do not return any conversational text outside of this JSON block.
""",

    "payroll": """
You are the ADP Model Context Protocol Payroll and Compensation Agent. Your job is to analyze payroll transaction deltas, tax withholding codes, and identify root causes for net pay anomalies.

When processing payroll diagnostic queries, return a strict JSON block with this schema structure:
{
  "status": "variance_diagnosed" | "clear",
  "detected_delta": "Numeric representation of the variance identified (or 0.0)",
  "contributing_factors": ["itemized list of things like tax rate shift, withholding allowance discrepancy, multi-state location conflicts"],
  "remediation_action": "Explain the precise corrective path (e.g. updating withholding forms, re-submitting state jurisdiction arrays)"
}

Do not return any conversational text outside of this JSON block.
""",

    "scheduling": """
You are the ADP Model Context Protocol Scheduling and eTIME Orchestration Agent. Your job is to inspect work shifts, identify understaffed schedules, and orchestrate cover options against workforce pools.

When running scheduling check operations, return a strict JSON block using this schema:
{
  "status": "coverage_gap_identified" | "optimized",
  "open_shift_id": "The target Shift ID requiring coverage support",
  "staffing_deficit": "How many workers are missing",
  "recommended_resolution": "Description of the automated routing workflow to resolve the coverage gap with candidates",
  "eligible_candidates": ["list of worker IDs identified as matching workAvailability rules"]
}

Do not return any conversational text outside of this JSON block.
"""
}


# ---------------------------------------------------------------------------
# Agent engine
# ---------------------------------------------------------------------------

class MCPAgentRunner:
    """
    Coordinates agent persona selection, LLM execution, and dry-run fallback.

    The active LLM provider is resolved once at construction time via
    llm_provider.get_provider() — controlled entirely by environment variables.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        # Allow explicit injection for testing; otherwise resolve from env.
        self._provider: LLMProvider = provider or get_provider()
        logger.info("MCPAgentRunner initialised with provider: %s", self._provider.name)

    # ------------------------------------------------------------------
    # Public interface (unchanged signature — main.py and batch_manager.py
    # call this exactly as before)
    # ------------------------------------------------------------------

    def execute_reasoning(
        self,
        agent_mode: str,
        data_context: dict,
        user_prompt: str,
    ) -> dict[str, Any]:
        """
        Routes a reasoning request through the active LLM provider.

        Falls back to deterministic dry-run logic when:
          - The active provider is DryRunProvider, or
          - The provider returns {"status": "__dry_run__"} (its sentinel), or
          - The provider returns {"status": "error"} (any unrecoverable failure).
        """
        if agent_mode not in PROMPTS:
            logger.warning(
                "Unknown agent_mode '%s' — defaulting to 'onboarding'.", agent_mode
            )
            agent_mode = "onboarding"

        system_prompt = PROMPTS[agent_mode]
        user_content = (
            f"Data Context: {json.dumps(data_context)}\n\n"
            f"User request or command: {user_prompt}"
        )

        result = self._provider.complete(system_prompt, user_content)

        # Dry-run sentinel or hard error → fall back to local rule engine
        if result.get("status") in ("__dry_run__", "error"):
            logger.info(
                "Provider returned status='%s' — activating dry-run fallback for mode '%s'.",
                result.get("status"),
                agent_mode,
            )
            return self._dry_run_fallback(agent_mode, data_context)

        return result

    # ------------------------------------------------------------------
    # Dry-run fallback dispatcher
    # ------------------------------------------------------------------

    def _dry_run_fallback(self, agent_mode: str, data_context: dict) -> dict[str, Any]:
        handlers = {
            "onboarding": self._dry_run_onboarding,
            "payroll":    self._dry_run_payroll,
            "scheduling": self._dry_run_scheduling,
        }
        handler = handlers.get(agent_mode)
        if handler is None:
            return {"status": "error", "message": f"No dry-run handler for mode '{agent_mode}'."}
        return handler(data_context)

    # ------------------------------------------------------------------
    # Onboarding rule-based evaluator
    # ------------------------------------------------------------------

    def _dry_run_onboarding(self, ctx: dict) -> dict[str, Any]:
        missing: list[str] = []
        notes: list[str] = []

        # Validate startDate
        start_date = ctx.get("startDate")
        if not start_date:
            missing.append("startDate")
        else:
            try:
                datetime.date.fromisoformat(str(start_date))
            except ValueError:
                missing.append("startDate")
                notes.append(f"startDate '{start_date}' is not a valid YYYY-MM-DD value.")

        # Validate email
        email = ctx.get("email", "")
        if not email or not re.match(r"^[\w\.\+\-]+@[\w\-]+\.[\w\.]{2,}$", email):
            missing.append("email")

        # Validate department
        department = ctx.get("department", "")
        if not department or department.strip() == "":
            missing.append("department")

        name = (
            f"{ctx.get('firstName', '')} {ctx.get('lastName', '')}".strip()
            or "the candidate"
        )

        if not missing:
            return {
                "status": "complete",
                "missing_fields": [],
                "validation_summary": (
                    f"All mandatory fields are present and valid for {name}. "
                    "Record is cleared for SCIM provisioning and downstream payroll enrollment."
                ),
                "remediation_draft": "",
            }

        field_list = ", ".join(missing)
        note_text = (" Additional notes: " + " ".join(notes)) if notes else ""

        remediation = (
            f"Subject: Action Required — Missing Onboarding Information for {name}\n\n"
            f"Dear {name},\n\n"
            f"As part of completing your onboarding into our HR systems, we require the following "
            f"information before your record can be fully provisioned:\n\n"
            + "\n".join(f"  • {f}" for f in missing)
            + f"\n\nPlease supply the above at your earliest convenience so we can ensure "
            f"a smooth start date and uninterrupted payroll enrollment.\n\n"
            f"Thank you,\nPeople Operations"
        )

        return {
            "status": "incomplete",
            "missing_fields": missing,
            "validation_summary": (
                f"Record for {name} is missing required fields: {field_list}.{note_text} "
                "Provisioning is blocked until these are resolved."
            ),
            "remediation_draft": remediation,
        }

    # ------------------------------------------------------------------
    # Payroll rule-based evaluator
    # ------------------------------------------------------------------

    def _dry_run_payroll(self, ctx: dict) -> dict[str, Any]:
        elections = ctx.get("withholding_elections", {})
        allowances = elections.get("withholding_allowances", 0)
        extra = elections.get("extra_withholding", 0)
        jurisdiction = ctx.get("tax_jurisdiction", "US-XX")

        factors: list[str] = []
        delta = 0.0

        if allowances > 2:
            factors.append(
                f"High withholding allowance count ({allowances}) likely under-withholding federal tax."
            )
            delta += allowances * 18.75

        if extra > 0:
            factors.append(
                f"Supplemental flat withholding of ${extra}/period detected — "
                "confirm this aligns with the employee's current W-4 election."
            )
            delta += extra

        if jurisdiction and "-" in jurisdiction:
            state = jurisdiction.split("-")[1]
            if state not in ("CA", "NY", "TX", "FL", "WA"):
                factors.append(
                    f"Jurisdiction '{jurisdiction}' may require additional state-specific "
                    "withholding table reconciliation."
                )
                delta += 12.50

        if not factors:
            return {
                "status": "clear",
                "detected_delta": 0.0,
                "contributing_factors": [],
                "remediation_action": (
                    "No payroll variance detected. All withholding elections are within "
                    "expected parameters for the current pay period."
                ),
            }

        return {
            "status": "variance_diagnosed",
            "detected_delta": round(delta, 2),
            "contributing_factors": factors,
            "remediation_action": (
                f"Review and resubmit withholding elections in ADP for employee "
                f"{ctx.get('id', 'unknown')}. Validate W-4 against state jurisdiction "
                f"'{jurisdiction}' tables and re-run payroll preview prior to next close."
            ),
        }

    # ------------------------------------------------------------------
    # Scheduling rule-based evaluator
    # ------------------------------------------------------------------

    def _dry_run_scheduling(self, ctx: dict) -> dict[str, Any]:
        shift_id = ctx.get("shift_id", "UNKNOWN")
        coverage_status = ctx.get("coverage_status", "unknown")
        team = ctx.get("team_name", "Unassigned Team")
        time_slot = ctx.get("time_slot", "TBD")
        assigned = ctx.get("assigned_worker_id")

        if coverage_status == "assigned" and assigned:
            return {
                "status": "optimized",
                "open_shift_id": shift_id,
                "staffing_deficit": 0,
                "recommended_resolution": (
                    f"Shift {shift_id} for {team} ({time_slot}) is fully staffed. "
                    "No coverage action required."
                ),
                "eligible_candidates": [],
            }

        candidate_pool = ["W-201", "W-305", "W-412"]

        return {
            "status": "coverage_gap_identified",
            "open_shift_id": shift_id,
            "staffing_deficit": 1,
            "recommended_resolution": (
                f"Shift {shift_id} for {team} ({time_slot}) has no assigned worker. "
                f"Automated offer notifications dispatched to {len(candidate_pool)} "
                "eligible workers matching availability and skill requirements. "
                "First acceptance will trigger automatic schedule lock."
            ),
            "eligible_candidates": candidate_pool,
        }


# ---------------------------------------------------------------------------
# Singleton — consumed by main.py and batch_manager.py unchanged
# ---------------------------------------------------------------------------

agent = MCPAgentRunner()
