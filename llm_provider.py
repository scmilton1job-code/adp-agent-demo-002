"""
llm_provider.py — LLM Provider Abstraction Layer
=================================================
Decouples agent.py from any specific LLM backend.

Usage
-----
The active provider is selected at startup via the LLM_PROVIDER environment variable:

    LLM_PROVIDER=gemini          → GeminiProvider  (default, uses GEMINI_API_KEY)
    LLM_PROVIDER=vertex          → VertexProvider   (uses GOOGLE_APPLICATION_CREDENTIALS + VERTEX_PROJECT)
    LLM_PROVIDER=anthropic       → AnthropicProvider (uses ANTHROPIC_API_KEY)
    LLM_PROVIDER=dry_run         → DryRunProvider   (no API key needed, for local/CI)
    LLM_PROVIDER=<unset or "">   → falls back to dry_run

Adding a new provider
---------------------
1. Subclass LLMProvider and implement complete().
2. Register it in PROVIDER_REGISTRY at the bottom of this file.
3. Set LLM_PROVIDER=<your_key> in the environment.
No other files need to change.

Cloud Run → ADP / Google Agent Garden migration path
------------------------------------------------------
When moving to ADP enterprise infrastructure or Google Agent Garden, create a new
subclass (e.g. AgentGardenProvider) that targets their endpoint, register it, and
flip the env var. The agent, routing, tools, and batch layers are untouched.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import re
import time
from typing import Any

import requests

logger = logging.getLogger("adp-agent.llm_provider")


# ---------------------------------------------------------------------------
# Shared helpers (used by multiple concrete providers)
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json … ``` wrappers that some models emit."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned


def _parse_json_response(text: str, provider_name: str) -> dict:
    """Clean and parse a JSON string returned by an LLM, with structured error fallback."""
    try:
        return json.loads(_strip_markdown_fences(text))
    except json.JSONDecodeError as exc:
        logger.error(
            "[%s] Failed to decode JSON response: %s\nRaw: %s",
            provider_name, exc, text,
        )
        return {
            "status": "error",
            "message": f"[{provider_name}] Agent returned malformed JSON. Raw output logged.",
        }


def _exponential_backoff_post(
    url: str,
    payload: dict,
    headers: dict,
    provider_name: str,
    max_retries: int = 5,
    timeout: int = 15,
) -> requests.Response | None:
    """
    Shared retry loop with exponential backoff.
    Returns the Response on 200, None after all retries are exhausted.
    """
    delays = [2 ** i for i in range(max_retries)]  # 1, 2, 4, 8, 16

    for attempt, delay in enumerate(delays):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                logger.warning(
                    "[%s] Rate-limited (attempt %d/%d) — backing off %ds.",
                    provider_name, attempt + 1, max_retries, delay,
                )
            else:
                logger.error(
                    "[%s] HTTP %d on attempt %d: %s",
                    provider_name, resp.status_code, attempt + 1, resp.text[:300],
                )
        except Exception as exc:
            logger.error("[%s] Request error (attempt %d): %s", provider_name, attempt + 1, exc)

        if attempt < max_retries - 1:
            time.sleep(delay)

    logger.error("[%s] All %d retries exhausted.", provider_name, max_retries)
    return None


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMProvider(abc.ABC):
    """
    Every LLM backend implements this single method.

    Parameters
    ----------
    system_prompt : str
        The agent persona / instructions (from PROMPTS in agent.py).
    user_content : str
        The serialized data context + user request.

    Returns
    -------
    dict
        A parsed JSON dict in the agent's expected schema.
        On failure, always returns {"status": "error", "message": "..."}.
    """

    @abc.abstractmethod
    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


# ---------------------------------------------------------------------------
# Gemini REST provider  (current default)
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """
    Targets the Gemini 2.5 Flash REST API directly.
    Requires: GEMINI_API_KEY
    Optional: GEMINI_MODEL (defaults to gemini-2.5-flash-preview-09-2025)
    """

    DEFAULT_MODEL = "gemini-2.5-flash-preview-09-2025"

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", self.DEFAULT_MODEL)
        self._base = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{self.model}:generateContent"
        )

    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        if not self.api_key:
            logger.error("[GeminiProvider] GEMINI_API_KEY not set.")
            return {"status": "error", "message": "GEMINI_API_KEY is not configured."}

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"responseMimeType": "application/json"},
        }

        resp = _exponential_backoff_post(
            url=f"{self._base}?key={self.api_key}",
            payload=payload,
            headers={"Content-Type": "application/json"},
            provider_name=self.name,
        )

        if resp is None:
            return {
                "status": "error",
                "message": "Gemini API unavailable after maximum retries.",
            }

        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_response(raw, self.name)


# ---------------------------------------------------------------------------
# Vertex AI provider  (Cloud Run service account / ADC auth)
# ---------------------------------------------------------------------------

class VertexProvider(LLMProvider):
    """
    Targets Vertex AI Generative Language API using Application Default Credentials.
    Requires: VERTEX_PROJECT, VERTEX_LOCATION (default: us-central1)
    Optional: VERTEX_MODEL (default: gemini-2.5-flash-001)

    Authentication: set GOOGLE_APPLICATION_CREDENTIALS or run on a GCP service
    account with aiplatform.endpoints.predict permission.

    This is the recommended path when moving to ADP's GCP enterprise org —
    swap LLM_PROVIDER=vertex, point at the org's project, done.
    """

    DEFAULT_MODEL = "gemini-2.5-flash-001"

    def __init__(self) -> None:
        self.project = os.getenv("VERTEX_PROJECT", "")
        self.location = os.getenv("VERTEX_LOCATION", "us-central1")
        self.model = os.getenv("VERTEX_MODEL", self.DEFAULT_MODEL)

    def _get_access_token(self) -> str:
        """Fetch a short-lived token from the GCE metadata server (works on Cloud Run automatically)."""
        try:
            resp = requests.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
                timeout=5,
            )
            resp.raise_for_status()
            return resp.json()["access_token"]
        except Exception as exc:
            logger.error("[VertexProvider] Failed to fetch access token: %s", exc)
            return ""

    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        if not self.project:
            return {"status": "error", "message": "VERTEX_PROJECT env var not set."}

        token = self._get_access_token()
        if not token:
            return {"status": "error", "message": "Could not obtain Vertex AI access token."}

        endpoint = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}"
            f"/locations/{self.location}/publishers/google/models/{self.model}:generateContent"
        )

        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"responseMimeType": "application/json"},
        }

        resp = _exponential_backoff_post(
            url=endpoint,
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            provider_name=self.name,
        )

        if resp is None:
            return {"status": "error", "message": "Vertex AI unavailable after maximum retries."}

        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_response(raw, self.name)


# ---------------------------------------------------------------------------
# Anthropic / Claude provider
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """
    Targets the Anthropic Messages API.
    Requires: ANTHROPIC_API_KEY
    Optional: ANTHROPIC_MODEL (default: claude-sonnet-4-6)
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("ANTHROPIC_MODEL", self.DEFAULT_MODEL)

    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "error", "message": "ANTHROPIC_API_KEY is not configured."}

        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }

        resp = _exponential_backoff_post(
            url="https://api.anthropic.com/v1/messages",
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            provider_name=self.name,
        )

        if resp is None:
            return {"status": "error", "message": "Anthropic API unavailable after maximum retries."}

        raw = resp.json()["content"][0]["text"]
        return _parse_json_response(raw, self.name)


# ---------------------------------------------------------------------------
# Agent Garden provider stub
# ---------------------------------------------------------------------------

class AgentGardenProvider(LLMProvider):
    """
    Stub for Google Agent Garden / ADP enterprise deployment.

    When ADP's infrastructure team provides endpoint details, implement
    complete() here — the rest of the stack (agent.py, main.py, batch_manager.py)
    requires zero changes.

    Requires (when implemented):
        AGENT_GARDEN_ENDPOINT  — full HTTPS URL to the inference endpoint
        AGENT_GARDEN_API_KEY   — API key or bearer token
    """

    def __init__(self) -> None:
        self.endpoint = os.getenv("AGENT_GARDEN_ENDPOINT", "")
        self.api_key = os.getenv("AGENT_GARDEN_API_KEY", "")

    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        if not self.endpoint:
            logger.warning(
                "[AgentGardenProvider] AGENT_GARDEN_ENDPOINT not set — "
                "this provider is not yet implemented. Returning stub response."
            )
            return {
                "status": "error",
                "message": (
                    "AgentGardenProvider is a stub. Set AGENT_GARDEN_ENDPOINT and "
                    "implement complete() with the target endpoint's request schema."
                ),
            }

        # TODO: implement when endpoint schema is confirmed by ADP/Google infra team.
        # Likely pattern: POST self.endpoint with Bearer auth and a payload shaped
        # like Vertex AI's generateContent request.
        raise NotImplementedError("AgentGardenProvider.complete() is not yet implemented.")


# ---------------------------------------------------------------------------
# Dry-run provider  (zero dependencies, always available)
# ---------------------------------------------------------------------------

class DryRunProvider(LLMProvider):
    """
    Returns a canned acknowledgement so the full stack can be exercised
    without any API credentials. The real rule-based evaluation logic lives
    in agent.py (_dry_run_* methods) — this provider just signals that no
    live LLM was called.
    """

    def complete(self, system_prompt: str, user_content: str) -> dict[str, Any]:
        logger.info("[DryRunProvider] Returning offline placeholder — no LLM called.")
        return {
            "status": "__dry_run__",
            "message": "DryRunProvider active. Real evaluation handled by agent fallback logic.",
        }


# ---------------------------------------------------------------------------
# Provider registry and factory
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "gemini":       GeminiProvider,
    "vertex":       VertexProvider,
    "anthropic":    AnthropicProvider,
    "agent_garden": AgentGardenProvider,
    "dry_run":      DryRunProvider,
}


def get_provider() -> LLMProvider:
    """
    Instantiates and returns the active LLM provider.

    Selection order:
    1. LLM_PROVIDER env var (explicit)
    2. Auto-detect: if GEMINI_API_KEY is set → gemini
    3. Auto-detect: if ANTHROPIC_API_KEY is set → anthropic
    4. Auto-detect: if VERTEX_PROJECT is set → vertex
    5. Fallback → dry_run (always safe, never raises)
    """
    provider_key = os.getenv("LLM_PROVIDER", "").strip().lower()

    if not provider_key:
        # Auto-detect from available credentials
        if os.getenv("GEMINI_API_KEY"):
            provider_key = "gemini"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider_key = "anthropic"
        elif os.getenv("VERTEX_PROJECT"):
            provider_key = "vertex"
        else:
            provider_key = "dry_run"
        logger.info("LLM_PROVIDER not set — auto-detected: '%s'", provider_key)

    if provider_key not in PROVIDER_REGISTRY:
        logger.error(
            "Unknown LLM_PROVIDER='%s'. Valid options: %s. Falling back to dry_run.",
            provider_key,
            list(PROVIDER_REGISTRY.keys()),
        )
        provider_key = "dry_run"

    provider = PROVIDER_REGISTRY[provider_key]()
    logger.info("Active LLM provider: %s", provider.name)
    return provider
