import os
import re
import json
import time
import requests
import logging
import datetime

logger = logging.getLogger("adp-agent.engine")

# --- Specialized Multi-Agent System Prompts ---

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


# --- Resilient Gemini API Execution Client ---

class GeminiMCPRunner:
    """
    Direct HTTPS REST wrapper targeting the Gemini 2.5 Flash API endpoint.
    Maintains zero-dependency footprint and implements resilient exponential backoff retry loops.
    """
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model_name = "gemini-2.5-flash-preview-09-2025"
        self.endpoint_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{self.model_name}:generateContent"
        )

    def execute_reasoning(self, agent_mode: str, data_context: dict, user_prompt: str) -> dict:
        """
        Coordinates execution prompts through Gemini with rigorous exponential backoff up to 5 retries.
        Falls back to deterministic dry-run logic when no API key is present.
        """
        if agent_mode not in PROMPTS:
            logger.warning(
                "Unknown agent_mode '%s' requested — defaulting to 'onboarding'.", agent_mode
            )
            agent_mode = "onboarding"

        if not self.api_key:
            logger.warning(
                "GEMINI_API_KEY is not configured in environment. Using offline dry-run logic."
            )
            return self._generate_dry_run_fallback(agent_mode, data_context)

        system_instruction = PROMPTS[agent_mode]
        user_query_content = (
            f"Data Context: {json.dumps(data_context)}\n\n"
            f"User request or command: {user_prompt}"
        )

        payload = {
            "contents": [{"parts": [{"text": user_query_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"responseMimeType": "application/json"},
        }

        url_with_key = f"{self.endpoint_url}?key={self.api_key}"
        retry_delays = [1, 2, 4, 8, 16]

        for attempt, delay in enumerate(retry_delays):
            try:
                response = requests.post(
                    url_with_key,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=15,
                )
                if response.status_code == 200:
                    result_json = response.json()
                    raw_text = result_json["candidates"][0]["content"]["parts"][0]["text"]
                    return self._clean_and_parse_json(raw_text)
                elif response.status_code == 429:
                    logger.warning("Rate-limited on attempt %d/%d — backing off.", attempt + 1, len(retry_delays))
                else:
                    logger.error(
                        "API invocation failed with code %d: %s",
                        response.status_code,
                        response.text,
                    )
            except Exception as e:
                logger.error("Error during API request (attempt %d): %s", attempt + 1, str(e))

            if attempt < len(retry_delays) - 1:
                time.sleep(delay)

        return {
            "status": "error",
            "message": "The downstream Gemini engine is temporarily unavailable after 5 retries.",
        }

    # ------------------------------------------------------------------
    # JSON hygiene
    # ------------------------------------------------------------------

    def _clean_and_parse_json(self, text: str) -> dict:
        """
        Defensively strips markdown fences before passing output to JSON decoder.
        """
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("Failed to decode Gemini JSON response: %s\nRaw text: %s", exc, text)
            return {
                "status": "error",
                "message": "Agent returned malformed JSON. Raw output logged for inspection.",
            }

    # ------------------------------------------------------------------
    # Deterministic dry-run fallback (no API key needed)
    # ------------------------------------------------------------------

    def _generate_dry_run_fallback(self, agent_mode: str, data_context: dict) -> dict:
        """
        Performs local rule-based evaluation so the demo works end-to-end
        without a Gemini API key. Each agent mode applies its own logic.
        """
        if agent_mode == "onboarding":
            return self._dry_run_onboarding(data_context)
        elif agent_mode == "payroll":
            return self._dry_run_payroll(data_context)
        elif agent_mode == "scheduling":
            return self._dry_run_scheduling(data_context)
        # Should never reach here after the mode guard above, but be safe.
        return {"status": "error", "message": f"No dry-run handler for mode '{agent_mode}'."}

    def _dry_run_onboarding(self, ctx: dict) -> dict:
        missing = []
        notes = []

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
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            missing.append("email")

        # Validate department
        department = ctx.get("department", "")
        if not department or department.strip() == "":
            missing.append("department")

        name = f"{ctx.get('firstName', '')} {ctx.get('lastName', '')}".strip() or "the candidate"

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
            + f"\n\nPlease supply the above at your earliest convenience so we can ensure a smooth "
            f"start date and uninterrupted payroll enrollment.\n\n"
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

    def _dry_run_payroll(self, ctx: dict) -> dict:
        elections = ctx.get("withholding_elections", {})
        allowances = elections.get("withholding_allowances", 0)
        extra = elections.get("extra_withholding", 0)
        jurisdiction = ctx.get("tax_jurisdiction", "US-XX")

        factors = []
        delta = 0.0

        if allowances > 2:
            factors.append(
                f"High withholding allowance count ({allowances}) likely under-withholding federal tax."
            )
            delta += allowances * 18.75

        if extra > 0:
            factors.append(
                f"Supplemental flat withholding of ${extra}/period detected — "
                "confirm this aligns with employee's current W-4 election."
            )

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

    def _dry_run_scheduling(self, ctx: dict) -> dict:
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

        # Simulate a pool of available workers drawn from the employees table concept
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


# Singleton agent instance consumed by main.py and batch_manager.py
agent = GeminiMCPRunner()
