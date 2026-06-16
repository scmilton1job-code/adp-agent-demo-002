import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List

from tools import (
    get_candidate_from_ats,
    get_employee_from_adp,
    get_schedule_details,
    transform_to_scim_format,
    execute_tax_withholding_write,
    execute_etime_coverage_write,
    execute_ksao_profile_write,
    terminate_employee,
    update_employee_fields,
)
from agent import agent
from batch_manager import batch_engine
from mcp_registry import (
    list_toolboxes,
    list_toolbox_tools,
    normalize_runtime_context,
    resolve_intent,
    resolve_tool_request,
)

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("adp-agent.api")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class InvokeRequest(BaseModel):
    action: str
    input: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)

class TaxWithholdingUpdate(BaseModel):
    employeeId: str
    stateJurisdiction: str
    withholdingElections: dict

class ScheduleSwapRequest(BaseModel):
    managerId: str
    shiftId: str
    action: str
    eligibleWorkerIds: List[str]

class TalentProfileSync(BaseModel):
    employeeId: str
    completedProject: str
    skillsAcquired: List[str]


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="ADP Model Context Protocol (MCP) Server Gateway", version="2.1")


@app.get("/")
def root():
    return {
        "status": "healthy",
        "service": "ADP MCP Integration Engine",
        "engine_architecture": "Decoupled Multi-Agent Platform Edge",
    }


@app.get("/capabilities")
def capabilities():
    return {
        "agent": "adp-mcp-orchestration-hub",
        "version": "2.1",
        "marketplace_mode": "feature-canonical",
        "active_capabilities": list_toolboxes(),
    }


@app.get("/marketplace/mcp/toolboxes")
def marketplace_toolboxes():
    return {
        "status": "success",
        "toolboxes": list_toolboxes(),
    }


@app.get("/marketplace/mcp/toolboxes/{toolbox_key}/tools")
def marketplace_tools_list(
    toolbox_key: str,
    sor: str = "RUN",
    region: str = "US & CAN",
    persona: str = "Integration Tester",
    rollout_phase: str = "1.5",
):
    runtime_context = normalize_runtime_context(
        {
            "sor": sor,
            "region": region,
            "persona": persona,
            "rollout_phase": rollout_phase,
        }
    )
    try:
        tools = list_toolbox_tools(toolbox_key, runtime_context)
        return {
            "status": "success",
            "toolbox_key": toolbox_key,
            "runtime_context": runtime_context,
            "tools": tools,
        }
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": str(exc)},
        )


# ---------------------------------------------------------------------------
# Core invoke router
# ---------------------------------------------------------------------------

@app.post("/invoke")
def invoke(request: InvokeRequest):
    action = resolve_intent(request.action)
    runtime_context = normalize_runtime_context(request.runtime_context)
    logger.info(
        "Invoke — resolved action='%s' (raw='%s') input=%s runtime_context=%s",
        action,
        request.action,
        request.input,
        runtime_context,
    )

    try:
        mcp_resolution = resolve_tool_request(action, runtime_context)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": str(exc)},
        )

    if not mcp_resolution["can_execute"]:
        return JSONResponse(
            status_code=403,
            content={
                "status": "blocked",
                "message": mcp_resolution["reason"],
                "mcp_resolution": mcp_resolution,
            },
        )

    # ── 1. Onboarding ──────────────────────────────────────────────────────
    if action == "hire_employee":
        candidate_id = str(request.input.get("candidateId", "101"))
        candidate = get_candidate_from_ats(candidate_id)
        if not candidate:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"Candidate '{candidate_id}' not found in ATS."},
            )

        agent_resp = agent.execute_reasoning(
            agent_mode="onboarding",
            data_context=candidate,
            user_prompt=f"Assess suitability for hire: Candidate ID {candidate_id}",
        )

        scim_data = None
        if agent_resp.get("status") == "complete":
            scim_data = transform_to_scim_format(candidate)

        return {
            "status": "success" if agent_resp.get("status") == "complete" else "incomplete",
            "agent_response": agent_resp,
            "scim_schema": scim_data,
            "mcp_resolution": mcp_resolution,
        }

    # ── 2. Payroll variance ────────────────────────────────────────────────
    elif action == "diagnose_pay_variance":
        employee_id = str(request.input.get("employeeId", "789"))
        employee = get_employee_from_adp(employee_id)
        if not employee:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"Employee record '{employee_id}' not found."},
            )

        agent_resp = agent.execute_reasoning(
            agent_mode="payroll",
            data_context=employee,
            user_prompt=f"Diagnose net pay delta anomalies on employee ID {employee_id}",
        )
        return {
            "status": "success",
            "agent_response": agent_resp,
            "metadata_evaluated": {"employeeId": employee_id, "payroll_system": "iPay"},
            "mcp_resolution": mcp_resolution,
        }

    # ── 3. Schedule coverage ───────────────────────────────────────────────
    elif action == "orchestrate_schedule_coverage":
        shift_id = str(request.input.get("shiftId", "S-902"))
        shift = get_schedule_details(shift_id)
        if not shift:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"Shift ID '{shift_id}' not located in schedules."},
            )

        agent_resp = agent.execute_reasoning(
            agent_mode="scheduling",
            data_context=shift,
            user_prompt=f"Verify staffing minimum exceptions on shift {shift_id}",
        )
        return {
            "status": "success",
            "agent_response": agent_resp,
            "metadata_evaluated": {"shiftId": shift_id, "WFM_system": "eTIME"},
            "mcp_resolution": mcp_resolution,
        }

    # ── 4. Terminate ───────────────────────────────────────────────────────
    elif action == "terminate_employee":
        employee_id = str(request.input.get("employeeId", "456"))
        try:
            result = terminate_employee(employee_id)
            return {"status": "success", **result, "mcp_resolution": mcp_resolution}
        except ValueError as e:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": str(e)},
            )
        except Exception as e:
            logger.error("Terminate failed for employee %s: %s", employee_id, e)
            raise HTTPException(status_code=500, detail=str(e))

    # ── 5. Update ──────────────────────────────────────────────────────────
    elif action == "update_employee":
        employee_id = str(request.input.get("employeeId", "789"))
        fields = request.input.get("fields", {})
        try:
            result = update_employee_fields(employee_id, fields)
            return {"status": "success", **result, "mcp_resolution": mcp_resolution}
        except ValueError as e:
            # Could be not-found (404) or no valid fields (422)
            msg = str(e)
            status_code = 422 if "Allowed:" in msg else 404
            return JSONResponse(
                status_code=status_code,
                content={"status": "error", "message": msg},
            )
        except Exception as e:
            logger.error("Update failed for employee %s: %s", employee_id, e)
            raise HTTPException(status_code=500, detail=str(e))

    else:
        raise HTTPException(status_code=400, detail=f"Action '{request.action}' is not supported.")


# ---------------------------------------------------------------------------
# Write-back handlers
# ---------------------------------------------------------------------------

@app.post("/invoke/payroll/tax-withholding")
def update_tax_withholding(payload: TaxWithholdingUpdate):
    logger.info("Write-back: state withholding elections for employee %s.", payload.employeeId)
    try:
        result = execute_tax_withholding_write(
            payload.employeeId, payload.stateJurisdiction, payload.withholdingElections
        )
        return {"status": "success", "mcp_handler": "taxWithholding_write", "details": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Tax withholding write failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/invoke/etime/schedule-orchestration")
def orchestrate_schedule_coverage(payload: ScheduleSwapRequest):
    logger.info("Write-back: scheduling coverage for shift %s.", payload.shiftId)
    try:
        result = execute_etime_coverage_write(
            payload.shiftId, payload.action, payload.eligibleWorkerIds
        )
        return {"status": "success", "mcp_handler": "cover_drop_swap_write", "details": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("eTIME coverage write failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hooks/project-complete")
def sync_talent_profile(payload: TalentProfileSync):
    logger.info("Webhook: KSAOC profile sync for employee %s.", payload.employeeId)
    try:
        result = execute_ksao_profile_write(payload.employeeId, payload.skillsAcquired)
        return {"status": "success", "mcp_handler": "ksao_profile_sync", "details": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("KSAO profile sync failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Async batch endpoints
# ---------------------------------------------------------------------------

@app.post("/invoke/batch-file")
def invoke_batch_file(file: UploadFile = File(...)):
    """
    Accepts a CSV upload, registers a background job, and returns a job_id
    immediately. Poll /invoke/batch-status/{job_id} for progress.
    """
    logger.info("Batch upload received: filename='%s'", file.filename)
    try:
        contents = file.file.read()
        job_id = batch_engine.submit_csv_job(contents)
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "job_id": job_id,
                "message": "Batch job queued. Poll /invoke/batch-status/{job_id} for results.",
            },
        )
    except Exception as e:
        logger.error("Failed to enqueue batch job: %s", str(e))
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal fault: {str(e)}"},
        )


@app.get("/invoke/batch-status/{job_id}")
def get_batch_status(job_id: str):
    """
    Returns current progress and partial results for a running or completed batch job.
    """
    job = batch_engine.get_job_status(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Job '{job_id}' not found."},
        )

    progress_pct = (
        round((job["completed"] / job["total"]) * 100) if job["total"] > 0 else 0
    )

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": {
            "completed": job["completed"],
            "total": job["total"],
            "percent": progress_pct,
        },
        "metadata": job.get("metadata"),
        "provisioned_records": job["provisioned"],
        "blocked_records": job["blocked"],
    }


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------

@app.get("/debug/scim/{candidate_id}")
def debug_scim_transform(candidate_id: str):
    candidate = get_candidate_from_ats(candidate_id)
    if not candidate:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Candidate profile not found."},
        )
    return {"status": "success", "scim_format": transform_to_scim_format(candidate)}