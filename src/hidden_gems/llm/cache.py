"""History-backed LLM cache keyed by content, prompt, schema and model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from dataclasses import replace

from ..common.time import utcnow
from ..models import DeepAnalysis
from .base import LLMBudget
from .validator import PROMPT_VERSION, SCHEMA_VERSION


class CachedLLMProvider:
    """Reuses stored analyses; performs a provider call only on a cache miss."""

    def __init__(
        self,
        provider: Any,
        store: Any,
        *,
        run_id: str,
        model: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: str = SCHEMA_VERSION,
        budget: LLMBudget | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._run_id = run_id
        self.model = model
        self.prompt_version = prompt_version
        self.schema_version = schema_version
        self.budget = budget if budget is not None else getattr(provider, "budget", None)

    def analyze_repository(self, evidence: Mapping[str, Any], *, now: datetime | None = None) -> DeepAnalysis:
        repo_id = int(evidence.get("github_repo_id") or 0)
        content_hash = str(evidence.get("relevant_content_hash") or "")
        if repo_id and content_hash:
            cached = self._store.find_llm_analysis(
                github_repo_id=repo_id,
                relevant_content_hash=content_hash,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
                model=self.model,
            )
            if cached is not None:
                if self.budget is not None:
                    self.budget.record_cache_hit()
                return replace(cached, source="CACHE")

        analysis = self._provider.analyze_repository(dict(evidence))
        if repo_id and content_hash and analysis.status == "OK":
            self._store.save_llm_analysis(
                repo_id,
                run_id=self._run_id,
                analyzed_at=now or utcnow(),
                relevant_content_hash=content_hash,
                prompt_version=self.prompt_version,
                schema_version=self.schema_version,
                model=self.model,
                analysis=analysis,
            )
        return analysis
