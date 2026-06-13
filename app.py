import os
import time
import requests
import streamlit as st
import json

# ---------------------------------------------------------------------------
# SSL helper
# ---------------------------------------------------------------------------

def _ssl_verify_setting():
    ca_bundle = (
        os.getenv("REQUESTS_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("ADP_CA_BUNDLE")
    )
    if ca_bundle:
        return ca_bundle
    flag = os.getenv("ADP_VERIFY_SSL", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


# ---------------------------------------------------------------------------
# Backend URL — never hard-coded
# ---------------------------------------------------------------------------

CLOUD_RUN_URL = os.getenv(
    "ADP_BACKEND_URL",
    "http://localhost:8000",   # safe local default for development
).rstrip("/")


# ---------------------------------------------------------------------------
# Intent mapping mirrors main.py so the UI can build correct payloads
# without raw string matching on the user's message.
# ---------------------------------------------------------------------------

INTENT_MAP = {
    "hire_employee":              ["hire", "onboard", "provision", "add employee", "new hire"],
    "diagnose_pay_variance":      ["variance", "payroll", "net pay", "withholding", "pay delta", "compensation"],
    "orchestrate_schedule_coverage": ["schedule", "etime", "shift", "coverage", "staffing"],
    "terminate_employee":         ["terminate", "offboard", "separation"],
    "update_employee":            ["update", "modify", "change", "edit", "patch"],
}

DEFAULT_INPUTS = {
    "hire_employee":              lambda digits: {"candidateId": digits or "101"},
    "diagnose_pay_variance":      lambda digits: {"employeeId":  digits or "789"},
    "orchestrate_schedule_coverage": lambda _: {"shiftId": "S-902"},
    "terminate_employee":         lambda digits: {"employeeId":  digits or "456"},
    "update_employee":            lambda digits: {"employeeId":  digits or "789",
                                                   "fields": {"status": "re-triggered"}},
}


def resolve_intent(text: str) -> tuple[str, dict]:
    """
    Returns (canonical_action, input_payload) from free-form user text.
    Falls back to update_employee if nothing matches.
    """
    lowered = text.lower()
    digits = "".join(filter(str.isdigit, text))

    for canonical, keywords in INTENT_MAP.items():
        if any(kw in lowered for kw in keywords):
            return canonical, DEFAULT_INPUTS[canonical](digits)

    return "update_employee", DEFAULT_INPUTS["update_employee"](digits)


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(page_title="ADP Onboarding Copilot", page_icon="🤖", layout="wide")

st.markdown("""
<style>
    .badge-success {
        background-color: #D1FAE5; color: #065F46;
        padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: .85em;
    }
    .badge-warning {
        background-color: #FEF3C7; color: #92400E;
        padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: .85em;
    }
    .badge-info {
        background-color: #DBEAFE; color: #1E3A8A;
        padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: .85em;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.markdown("# 🎛️ Integration Core")
st.sidebar.caption(f"Backend: `{CLOUD_RUN_URL}`")

if st.sidebar.button("🔌 Ping FastAPI Gateway"):
    try:
        resp = requests.get(CLOUD_RUN_URL, verify=_ssl_verify_setting(), timeout=5)
        if resp.status_code == 200:
            st.sidebar.success("Gateway online!")
        else:
            st.sidebar.error(f"Status: {resp.status_code}")
    except Exception:
        st.sidebar.error("Connection timed out.")

active_agent = st.sidebar.selectbox(
    "🤖 Active Agent Persona",
    ["Onboarding Agent", "Payroll Variance Agent", "Workforce Scheduling Agent"],
)

descriptions = {
    "Onboarding Agent":           "Reviewing onboarding eligibility & SCIM standard formats.",
    "Payroll Variance Agent":     "Analyzing state withholding deltas and net pay variances.",
    "Workforce Scheduling Agent": "Orchestrating team staffing gaps and schedule swaps.",
}
st.sidebar.info(descriptions[active_agent])
st.sidebar.markdown("---")

# ---------------------------------------------------------------------------
# Batch processing — async with live progress bar
# ---------------------------------------------------------------------------

st.sidebar.markdown("### 🗂️ Batch Processing Gateway")
uploaded_file = st.sidebar.file_uploader("Upload Practitioner Spreadsheet (CSV)", type=["csv"])

if uploaded_file is not None:
    if st.sidebar.button("▶️ Start Batch Job"):
        with st.sidebar.status("Submitting batch file…") as status_box:
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")}
                submit_resp = requests.post(
                    f"{CLOUD_RUN_URL}/invoke/batch-file",
                    files=files,
                    verify=_ssl_verify_setting(),
                    timeout=15,
                )

                if submit_resp.status_code not in (200, 202):
                    st.sidebar.error(f"Server rejected upload: HTTP {submit_resp.status_code}")
                else:
                    job_id = submit_resp.json().get("job_id")
                    status_box.update(label=f"Job `{job_id[:8]}…` queued — polling…")

                    progress_bar = st.sidebar.progress(0, text="Processing rows…")

                    # Poll until done (max 120 s)
                    deadline = time.time() + 120
                    while time.time() < deadline:
                        poll = requests.get(
                            f"{CLOUD_RUN_URL}/invoke/batch-status/{job_id}",
                            verify=_ssl_verify_setting(),
                            timeout=10,
                        ).json()

                        pct = poll.get("progress", {}).get("percent", 0)
                        completed = poll.get("progress", {}).get("completed", 0)
                        total = poll.get("progress", {}).get("total", 1)
                        progress_bar.progress(pct / 100, text=f"Processed {completed}/{total} rows…")

                        if poll.get("status") == "complete":
                            break
                        time.sleep(1.5)

                    progress_bar.empty()
                    meta = poll.get("metadata", {})
                    status_box.update(label="Batch complete!", state="complete")
                    st.sidebar.success(
                        f"✅ **{meta.get('fully_provisioned_count', 0)}** provisioned  "
                        f"⚠️ **{meta.get('action_blocked_count', 0)}** blocked"
                    )

                    with st.expander("📊 Batch Execution Details", expanded=True):
                        st.json(poll)

            except Exception as e:
                st.sidebar.error(f"Batch job failed: {e}")


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.markdown("## 🤖 ADP Onboarding Copilot")
st.markdown(
    "`Platform Innovation` &middot; `Model Context Protocol v2.1` &middot; "
    "`Centralized Integration Gateway` &middot; `Multi-Agent Routing`"
)
st.markdown("---")

# Chat state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                f"Hello! I'm running on the **{active_agent}** engine. "
                "Try: *hire employee 101* · *analyze payroll variance on employee 789* "
                "· *check schedule coverage for shift S-902*."
            ),
            "mode": active_agent,
        }
    ]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"], unsafe_allow_html=True)
        if msg.get("scim_payload"):
            with st.expander("📋 SCIM User Schema (RFC 7643)"):
                st.json(msg["scim_payload"])
        if msg.get("raw_a2a_json"):
            with st.expander("🔍 Raw A2A JSON"):
                st.json(msg["raw_a2a_json"])

# Suggestion chips
st.markdown("##### 💡 Pre-seeded test scenarios:")
cols = st.columns(3)
chip_prompt = None
with cols[0]:
    if st.button("Sarah Chen — Green Path (ID 101)"):
        chip_prompt = "hire employee 101"
with cols[1]:
    if st.button("Elena Vasquez — Amber Path (ID 201)"):
        chip_prompt = "hire employee 201"
with cols[2]:
    if st.button("Payroll Variance — Comp Delta (ID 789)"):
        chip_prompt = "analyze payroll variance on employee 789"

# Chat input
chat_input = st.chat_input("Try: hire employee 101 · payroll variance employee 789 · shift coverage S-902")
user_prompt = chip_prompt or chat_input

# ---------------------------------------------------------------------------
# Process user input
# ---------------------------------------------------------------------------

if user_prompt:
    st.session_state.messages.append({"role": "user", "content": user_prompt, "mode": active_agent})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # Resolve intent deterministically
    action_name, input_body = resolve_intent(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Invoking dynamic gateway…"):
            try:
                resp = requests.post(
                    f"{CLOUD_RUN_URL}/invoke",
                    json={"action": action_name, "input": input_body},
                    verify=_ssl_verify_setting(),
                    timeout=20,
                )

                if resp.status_code == 200:
                    api_data = resp.json()
                    agent_res = api_data.get("agent_response", {})
                    scim_payload = api_data.get("scim_schema")
                    status_val = agent_res.get("status") or api_data.get("status", "")

                    output = ""
                    if status_val == "complete":
                        output += '<div><span class="badge-success">✓ PROVISIONED</span></div>\n\n'
                        output += f"**Decision:** {agent_res.get('validation_summary')}\n\n"
                        output += "Identity provisioned into SCIM schema for downstream enrollment."
                    elif status_val == "incomplete":
                        output += '<div><span class="badge-warning">⚠️ ACTION BLOCKED</span></div>\n\n'
                        output += f"**Decision:** {agent_res.get('validation_summary')}\n\n"
                        output += f"**Missing:** `{agent_res.get('missing_fields')}`\n\n"
                        if agent_res.get("remediation_draft"):
                            output += f"**Draft notification:**\n```\n{agent_res['remediation_draft']}\n```"
                    else:
                        output += f'<div><span class="badge-info">ℹ️ {status_val.upper()}</span></div>\n\n'
                        if "validation_summary" in agent_res:
                            output += f"**Summary:** {agent_res['validation_summary']}\n"
                        elif "contributing_factors" in agent_res:
                            output += f"**Anomalies:** {agent_res['contributing_factors']}\n"
                            output += f"**Remediation:** {agent_res['remediation_action']}\n"
                        elif "recommended_resolution" in agent_res:
                            output += f"**Resolution:** {agent_res['recommended_resolution']}\n"
                            output += f"**Candidates dispatched:** {agent_res['eligible_candidates']}\n"
                        else:
                            output += f"**Message:** {api_data.get('message', 'Action processed.')}"

                    st.markdown(output, unsafe_allow_html=True)

                    if scim_payload:
                        with st.expander("📋 SCIM User Schema (RFC 7643)"):
                            st.json(scim_payload)
                    with st.expander("🔍 Raw A2A JSON"):
                        st.json(api_data)

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": output,
                        "mode": active_agent,
                        "scim_payload": scim_payload,
                        "raw_a2a_json": api_data,
                    })
                else:
                    err = f"Gateway returned HTTP {resp.status_code}."
                    st.error(err)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": err, "mode": active_agent}
                    )

            except Exception as e:
                err = f"Round-trip failed: {e}"
                st.error(err)
                st.session_state.messages.append(
                    {"role": "assistant", "content": err, "mode": active_agent}
                )