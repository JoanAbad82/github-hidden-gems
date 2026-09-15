"""DeepSeek provider: bounded, schema-validated, secret-safe (SPEC_V1 §8)."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import httpx

from ..config import AppConfig
from ..models import DeepAnalysis
from .base import LLMBudget, LLMProviderError, repo_from_evidence
from .validator import PROMPT_VERSION, LLMValidationError, to_deep_analysis, validate_llm_output

DEFAULT_PROMPT_PATH = "prompts/deep_analyzer_v1.txt"


class DeepSeekProvider:
    """HTTP provider with explicit timeouts, retries and no secret logging."""

    def __init__(
        self,
        config: AppConfig,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        budget: LLMBudget | None = None,
        prompt_path: str | None = None,
    ) -> None:
        self._config = config
        self._llm = config.llm
        self._api_key = api_key or os.environ.get(self._llm.api_key_env_var) or ""
        self._client = client
        self._owns_client = client is None
        self.budget = budget if budget is not None else LLMBudget(
            max_calls=self._llm.max_llm_calls_per_run,
            max_budget=self._llm.max_llm_budget_per_run,
        )
        self.prompt_version = PROMPT_VERSION
        self.model = self._llm.model
        prompt_file = config.root / (prompt_path or DEFAULT_PROMPT_PATH)
        self._prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else PROMPT_VERSION

    # -- helpers ----------------------------------------------------------

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._llm.timeout_seconds)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def _payload(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "model": self._llm.model,
            "messages": [
                {"role": "system", "content": self._prompt},
                {
                    "role": "user",
                    "content": json.dumps(evidence, ensure_ascii=True, sort_keys=True)[
                        : self._llm.max_input_tokens_per_repo * 4
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": self._llm.max_output_tokens_per_repo,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

    def _cost(self, usage: Mapping[str, Any]) -> float:
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return (
            input_tokens / 1000.0 * float(self._llm.cost_per_1k_input_tokens)
            + output_tokens / 1000.0 * float(self._llm.cost_per_1k_output_tokens)
        )

    # -- provider interface ----------------------------------------------

    def analyze_repository(self, evidence: Mapping[str, Any]) -> DeepAnalysis:
        repo = repo_from_evidence(evidence)
        if not self._api_key:
            raise LLMProviderError(
                f"missing API key in environment variable {self._llm.api_key_env_var}"
            )
        if not self.budget.can_call():
            raise LLMProviderError("LLM call budget exhausted for this run")

        attempts = int(self._llm.max_retries_per_candidate) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            if not self.budget.can_call():
                last_error = LLMProviderError("LLM call budget exhausted for this run")
                break
            try:
                response = self._http().post(
                    f"{self._llm.api_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._payload(evidence),
                )
            except httpx.HTTPError as exc:  # network-level failure
                last_error = LLMProviderError(f"provider request failed: {type(exc).__name__}")
                continue

            usage = {}
            if response.status_code >= 400:
                self.budget.record_call(reason="ERROR")
                last_error = LLMProviderError(f"provider returned HTTP {response.status_code}")
                continue
            try:
                body = response.json()
            except ValueError:
                self.budget.record_call(reason="INVALID")
                last_error = LLMProviderError("provider returned non-JSON response")
                continue

            usage = body.get("usage") or {}
            self.budget.record_call(
                reason="PRIMARY" if attempt == 0 else "RETRY",
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                cost=self._cost(usage),
            )
            try:
                content = body["choices"][0]["message"]["content"]
                payload = validate_llm_output(content)
            except (KeyError, IndexError, TypeError) as exc:
                last_error = LLMProviderError("provider response is missing choices/message/content")
                continue
            except LLMValidationError as exc:
                last_error = exc
                continue
            return to_deep_analysis(repo, payload)

        self.budget.record_failure()
        return DeepAnalysis(
            repo=repo,
            evidence={"llm_evidence": dict(evidence), "failure": type(last_error).__name__},
            relevance_suggestion=None,
            originality_suggestion=None,
            why_interesting=None,
            summary=None,
            risks=(f"LLM analysis unavailable: {last_error}",),
            confidence="LOW",
            status="LLM_FAILED",
            source="PROVIDER",
        )
