from __future__ import annotations

from copy import deepcopy

HEAT_MAP_OPTIONS = [
    "SOR Built - Agent Core",
    "SOR Built - Custom",
    "MKPL Built",
    "SOR Built - Beyond FY26",
    "SOR Built - Won't Do",
    "Not Applicable",
]

EXECUTABLE_STATUSES = {
    "SOR Built - Agent Core",
    "SOR Built - Custom",
    "MKPL Built",
}

PHASE_ORDER = {
    "1": 1.0,
    "1.5": 1.5,
    "2": 2.0,
}

DEFAULT_RUNTIME_CONTEXT = {
    "sor": "RUN",
    "region": "US & CAN",
    "persona": "Integration Tester",
    "rollout_phase": "1.5",
    "client_app": "adp-agent-demo-002",
}

INTENT_MAP = {
    "hire_employee": ["hire", "onboard", "provision", "add employee", "new hire"],
    "diagnose_pay_variance": ["variance", "payroll", "net pay", "withholding", "pay delta", "compensation"],
    "orchestrate_schedule_coverage": ["schedule", "etime", "shift", "coverage", "staffing"],
    "terminate_employee": ["terminate", "offboard", "separation", "let go", "fire"],
    "update_employee": ["update", "modify", "change", "edit", "patch"],
}

TOOLBOX_REGISTRY = {
    "worker_profile": {
        "display_name": "Worker Profile Toolbox",
        "feature_canonical": "mcp.hcm.worker-profile.toolbox",
        "server_path": "/hcm/mcp-toolboxes/v1/worker-profile",
        "domain": "HR",
        "phase": "1.5",
        "description": "Feature-level toolbox for worker profile retrieval and lifecycle updates.",
        "action_tools": {
            "hire_employee": {
                "tool_name": "mcp_validate_worker_onboarding_packet",
                "operation": "read",
                "phase": "1",
                "description": "Validates onboarding packet data before downstream provisioning.",
            },
            "update_employee": {
                "tool_name": "mcp_update_worker_profile",
                "operation": "write",
                "phase": "1.5",
                "description": "Updates whitelisted worker profile fields in the system of record.",
            },
            "terminate_employee": {
                "tool_name": "mcp_terminate_worker",
                "operation": "write",
                "phase": "2",
                "description": "Terminates a worker record in the authoritative system of record.",
            },
        },
        "heat_map": {
            "US & CAN": {
                "RUN": "SOR Built - Agent Core",
                "WFN CG": "SOR Built - Custom",
                "WFN NG": "MKPL Built",
            }
        },
        "tools": [
            {
                "tool_name": "mcp_view_worker_demographics_by_associate_id",
                "operation": "read",
                "phase": "1",
                "description": "Reads worker demographic context for onboarding and profile review.",
            },
            {
                "tool_name": "mcp_view_worker_names",
                "operation": "read",
                "phase": "1",
                "description": "Reads worker naming context for onboarding and profile review.",
            },
            {
                "tool_name": "mcp_view_worker_legal_address",
                "operation": "read",
                "phase": "1",
                "description": "Reads worker legal address data.",
            },
            {
                "tool_name": "mcp_view_worker_personal_address",
                "operation": "read",
                "phase": "1",
                "description": "Reads worker personal address data.",
            },
            {
                "tool_name": "mcp_update_worker_profile",
                "operation": "write",
                "phase": "1.5",
                "description": "Updates whitelisted worker profile fields in the system of record.",
            },
            {
                "tool_name": "mcp_terminate_worker",
                "operation": "write",
                "phase": "2",
                "description": "Terminates a worker record in the authoritative system of record.",
            },
        ],
    },
    "payroll": {
        "display_name": "Payroll Insights Toolbox",
        "feature_canonical": "mcp.payroll.worker-pay.toolbox",
        "server_path": "/payroll/mcp-toolboxes/v1/worker-pay",
        "domain": "Payroll",
        "phase": "1",
        "description": "Read-heavy payroll toolbox for compensation, tax, and pay diagnostic workflows.",
        "action_tools": {
            "diagnose_pay_variance": {
                "tool_name": "mcp_diagnose_pay_variance",
                "operation": "read",
                "phase": "1",
                "description": "Inspects withholding and compensation context for payroll variance.",
            }
        },
        "heat_map": {
            "US & CAN": {
                "RUN": "SOR Built - Agent Core",
                "WFN CG": "SOR Built - Agent Core",
                "WFN NG": "SOR Built - Custom",
            }
        },
        "tools": [
            {
                "tool_name": "mcp_view_worker_compensations_by_associate_id",
                "operation": "read",
                "phase": "1",
                "description": "Retrieves compensation context used by payroll variance diagnostics.",
            },
            {
                "tool_name": "mcp_view_direct_deposit",
                "operation": "read",
                "phase": "1",
                "description": "Surfaces pay-distribution context for payroll investigations.",
            },
            {
                "tool_name": "mcp_view_federal_tax_profile",
                "operation": "read",
                "phase": "1",
                "description": "Reads worker tax-election context for payroll diagnostics.",
            },
            {
                "tool_name": "mcp_diagnose_pay_variance",
                "operation": "read",
                "phase": "1",
                "description": "Inspects withholding and compensation context for payroll variance.",
            },
        ],
    },
    "workforce_scheduling": {
        "display_name": "Workforce Scheduling Toolbox",
        "feature_canonical": "mcp.time.schedule-coverage.toolbox",
        "server_path": "/time/mcp-toolboxes/v1/schedule-coverage",
        "domain": "Time",
        "phase": "2",
        "description": "Coverage orchestration toolbox for schedule routing and staffing actions.",
        "action_tools": {
            "orchestrate_schedule_coverage": {
                "tool_name": "mcp_orchestrate_schedule_coverage",
                "operation": "write",
                "phase": "2",
                "description": "Routes schedule coverage requests to the selected workforce SOR.",
            }
        },
        "heat_map": {
            "US & CAN": {
                "RUN": "SOR Built - Beyond FY26",
                "WFN CG": "SOR Built - Custom",
                "WFN NG": "Not Applicable",
            }
        },
        "tools": [
            {
                "tool_name": "mcp_orchestrate_schedule_coverage",
                "operation": "write",
                "phase": "2",
                "description": "Routes schedule coverage requests to the selected workforce SOR.",
            }
        ],
    },
}

ACTION_TO_TOOLBOX = {
    action: toolbox_key
    for toolbox_key, toolbox in TOOLBOX_REGISTRY.items()
    for action in toolbox["action_tools"]
}

PERSONA_DENY_RULES = {
    "EE": {"terminate_employee", "hire_employee"},
}


def resolve_intent(raw_action: str) -> str:
    lowered = raw_action.strip().lower()
    for canonical, keywords in INTENT_MAP.items():
        if any(keyword in lowered for keyword in keywords):
            return canonical
    return lowered


def normalize_runtime_context(runtime_context: dict | None) -> dict:
    normalized = deepcopy(DEFAULT_RUNTIME_CONTEXT)
    if runtime_context:
        for key, value in runtime_context.items():
            if value not in (None, ""):
                normalized[key] = value
    normalized["sor"] = str(normalized["sor"]).replace("_", " ").upper()
    normalized["region"] = str(normalized["region"]).replace("_", " ").upper()
    normalized["persona"] = str(normalized["persona"])
    return normalized


def _phase_enabled(required_phase: str, active_phase: str) -> bool:
    return PHASE_ORDER.get(active_phase, 0) >= PHASE_ORDER.get(required_phase, 99)


def _toolbox_heat_map_status(toolbox: dict, runtime_context: dict) -> str:
    region = runtime_context["region"]
    sor = runtime_context["sor"]
    region_map = toolbox["heat_map"].get(region, {})
    return region_map.get(sor, "Not Applicable")


def _tool_allowed_for_persona(action: str, runtime_context: dict) -> bool:
    denied = PERSONA_DENY_RULES.get(runtime_context["persona"], set())
    return action not in denied


def list_toolboxes() -> list[dict]:
    toolboxes = []
    for toolbox_key, toolbox in TOOLBOX_REGISTRY.items():
        toolboxes.append(
            {
                "toolbox_key": toolbox_key,
                "display_name": toolbox["display_name"],
                "feature_canonical": toolbox["feature_canonical"],
                "server_path": toolbox["server_path"],
                "phase": toolbox["phase"],
                "domain": toolbox["domain"],
                "description": toolbox["description"],
                "heat_map": toolbox["heat_map"],
                "tools": toolbox["tools"],
            }
        )
    return toolboxes


def list_toolbox_tools(toolbox_key: str, runtime_context: dict | None = None) -> list[dict]:
    if toolbox_key not in TOOLBOX_REGISTRY:
        raise ValueError(f"Unknown toolbox '{toolbox_key}'.")

    ctx = normalize_runtime_context(runtime_context)
    toolbox = TOOLBOX_REGISTRY[toolbox_key]
    status = _toolbox_heat_map_status(toolbox, ctx)
    if status not in EXECUTABLE_STATUSES:
        return []

    tools = []
    for tool in toolbox["tools"]:
        if _phase_enabled(tool["phase"], ctx["rollout_phase"]):
            tools.append(tool)

    for action, tool in toolbox["action_tools"].items():
        if _phase_enabled(tool["phase"], ctx["rollout_phase"]) and _tool_allowed_for_persona(action, ctx):
            if not any(existing["tool_name"] == tool["tool_name"] for existing in tools):
                tools.append(tool)
    return tools


def resolve_tool_request(action: str, runtime_context: dict | None = None) -> dict:
    if action not in ACTION_TO_TOOLBOX:
        raise ValueError(f"No registered MCP toolbox for action '{action}'.")

    ctx = normalize_runtime_context(runtime_context)
    toolbox_key = ACTION_TO_TOOLBOX[action]
    toolbox = TOOLBOX_REGISTRY[toolbox_key]
    tool = toolbox["action_tools"][action]
    heat_map_status = _toolbox_heat_map_status(toolbox, ctx)
    phase_enabled = _phase_enabled(tool["phase"], ctx["rollout_phase"])
    persona_allowed = _tool_allowed_for_persona(action, ctx)
    executable = heat_map_status in EXECUTABLE_STATUSES and phase_enabled and persona_allowed

    reason = None
    if heat_map_status not in EXECUTABLE_STATUSES:
        reason = (
            f"SOR heat-map status '{heat_map_status}' does not allow execution for "
            f"{ctx['sor']} in {ctx['region']}."
        )
    elif not phase_enabled:
        reason = (
            f"Tool '{tool['tool_name']}' is gated for phase {tool['phase']} and "
            f"current rollout is {ctx['rollout_phase']}."
        )
    elif not persona_allowed:
        reason = (
            f"Persona '{ctx['persona']}' is not permitted by the SOR policy to execute "
            f"tool '{tool['tool_name']}'."
        )

    return {
        "requested_action": action,
        "runtime_context": ctx,
        "toolbox_key": toolbox_key,
        "toolbox_name": toolbox["display_name"],
        "feature_canonical": toolbox["feature_canonical"],
        "server_path": toolbox["server_path"],
        "domain": toolbox["domain"],
        "tool_name": tool["tool_name"],
        "tool_phase": tool["phase"],
        "sor_support_status": heat_map_status,
        "phase_enabled": phase_enabled,
        "persona_allowed": persona_allowed,
        "can_execute": executable,
        "reason": reason,
        "available_tools": list_toolbox_tools(toolbox_key, ctx),
    }