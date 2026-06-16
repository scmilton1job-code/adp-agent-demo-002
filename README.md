# adp-agent-demo-002
This is an enterprise HR/payroll integration prototype built with FastAPI and Streamlit. It features a multi-agent persona pattern leveraging the Model Context Protocol (MCP) and Gemini to handle automated onboarding validation (SCIM/RFC 7643 compliance), payroll variance diagnostics, and asynchronous CSV batch processing.

The current POC also models Marketplace-style MCP control-plane concerns:
- feature-level canonicals that resolve to MCP toolboxes rather than individual URL operations
- SOR heat-map support across RUN, WFN CG, and WFN NG for US & CAN
- runtime filtering of available tools based on SOR, rollout phase, and persona
- explicit MCP routing metadata surfaced in API responses and the Streamlit UI
