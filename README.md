# ADP MCP Integration Engine (Demo 002.3)

This repository contains an enterprise HR/payroll integration prototype built with **FastAPI** and **Streamlit**. It demonstrates a Decoupled Multi-Agent Platform Edge architecture, leveraging the **Model Context Protocol (MCP)** to intelligently route natural language commands to specialized agent personas.

## ✨ Key Features

* **Multi-Agent Orchestration Engine:** Dynamically routes requests to three specialized personas:
  * **Onboarding Agent:** Validates candidate data, checks mandatory fields, and compiles strict RFC 7643 SCIM User Schemas.
  * **Payroll Agent:** Diagnoses net pay anomalies, withholding deltas, and multi-state tax jurisdiction conflicts.
  * **Scheduling Agent:** Orchestrates eTIME shift coverage, identifies staffing deficits, and dispatches automated candidate offers.
* **LLM Provider Abstraction:** A plug-and-play architecture (`llm_provider.py`) supporting **Gemini, Vertex AI, Anthropic**, and a stub for **Google Agent Garden**. Includes a deterministic `dry_run` fallback mode allowing full application testing without live API keys.
* **Asynchronous Batch Processing:** Bulk CSV practitioner uploads are parsed and processed via a non-blocking background thread pool, complete with live progress polling endpoints.
* **Workforce/ERP Financial Insights:** A deterministic SQL query layer simulating an integration between ATS/HCM data and ERP General Ledger transactions (featuring the mock *Northfield Outdoor Co.* dataset) to surface labor vs. budget variances.

---

## 🏗️ Project Structure

* `main.py`: The FastAPI backend gateway. Exposes `/invoke`, `/invoke/batch-file`, and direct `/insights/*` endpoints.
* `app.py`: The Streamlit frontend UI. Features a chat copilot, financial insights dashboard, and a drag-and-drop batch processing interface.
* `agent.py`: The `MCPAgentRunner` core. Contains system prompts and rule-based dry-run fallback evaluation logic.
* `llm_provider.py`: The LLM abstraction layer handling HTTP transport, retries, and JSON parsing.
* `batch_manager.py`: The `BatchProcessingEngine` for handling concurrent background execution of CSV rows.
* `tools.py`: SQLite mock database initialization (`mock_ats.db`), data seeding, read/write handlers, and SCIM transformations.

---

## 🚀 Quick Start

### 1. Install Dependencies
Make sure you are running Python 3.10+ and install the required packages:
```bash
pip install -r requirements.txt
