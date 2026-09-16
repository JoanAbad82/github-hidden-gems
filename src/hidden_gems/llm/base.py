"""Provider boundary and run-level LLM budgets (SPEC_V1 §8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ..models import DeepAnalysis, RepositoryRef


class LLMProviderError(RuntimeError):
    """Raised when the provider cannot be reached or answers unusably."""


class LLMBudgetExceeded(RuntimeError):
    """Raised when a run would exceed its configured LLM call budget."""


@dataclass
class LLMBudget:
    """Per-run accounting for calls, tokens, cost and safe attempt diagnostics."""

    max_calls: int = 0
    max_budget: float = 0.0
    calls_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    cache_hits: int = 0
    failures: int = 0
    _reasons: dict[str, int] = field(default_factory=dict)
    _attempts: list[dict[str, Any]] = field(default_factory=list)

    def can_call(self) -> bool:
        if self.calls_made >= self.max_calls:
            return False
        if self.max_budget and self.cost >= self.max_budget:
            return False
        return True

    def record_call(self, *, reason: str = "PRIMARY", input_tokens: int = 0, output_tokens: int = 0,
                    cost: float = 0.0) -> None:
        self.calls_made += 1
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)
        self.cost += float(cost or 0.0)
        self._reasons[reason] = self._reasons.get(reason, 0) + 1

    def record_attempt(
        self,
        *,
        repo_id: int,
        attempt: str,
        http_status: int | None,
        finish_reason: str | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        content_length: int = 0,
        validation_result: str,
    ) -> None:
        """Record bounded diagnostics only; never prompts, generated content, or secrets."""

        self._attempts.append(
            {
                "repo_id": int(repo_id),
                "attempt": str(attempt),
                "http_status": int(http_status) if http_status is not None else None,
                "finish_reason": str(finish_reason) if finish_reason is not None else None,
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
                "content_length": int(content_length or 0),
                "validation_result": str(validation_result),
            }
        )

    def record_cache_hit(self) -> None:
        self.cache_hits += 1

    def record_failure(self) -> None:
        self.failures += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls_made": self.calls_made,
            "max_calls": self.max_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": round(self.cost, 6),
            "cache_hits": self.cache_hits,
            "failures": self.failures,
            "reasons": dict(sorted(self._reasons.items())),
            "attempts": [dict(item) for item in self._attempts],
        }


class LLMProvider(Protocol):
    """Everything the pipeline needs from a semantic analysis provider."""

    def analyze_repository(self, evidence: dict[str, Any]) -> DeepAnalysis: ...


@dataclass
class DisabledLLMProvider:
    """`LLM_ENABLED=false`: deterministic, no model suggestions, pipeline continues."""

    model: str = "disabled"

    def analyze_repository(self, evidence: Mapping[str, Any]) -> DeepAnalysis:
        repo = repo_from_evidence(evidence)
        return DeepAnalysis(
            repo=repo,
            evidence={"llm_evidence": dict(evidence), "skipped": "LLM_DISABLED"},
            relevance_suggestion=None,
            originality_suggestion=None,
            why_interesting=None,
            summary=None,
            risks=(),
            confidence="LOW",
            status="OK",
            source="DISABLED",
        )


def repo_from_evidence(evidence: Mapping[str, Any]) -> RepositoryRef:
    """Rebuild the canonical repository reference from a deep evidence bundle."""

    payload = evidence.get("repository") if isinstance(evidence, Mapping) else None
    if isinstance(payload, Mapping):
        return RepositoryRef(
            github_repo_id=int(payload["github_repo_id"]),
            owner=str(payload["full_name"]).split("/")[0],
            name=str(payload["full_name"]).split("/")[1],
            full_name=str(payload["full_name"]),
            html_url=str(payload.get("html_url") or f"https://github.com/{payload['full_name']}"),
        )
    full_name = str(evidence.get("repo") or "")
    owner, _, name = full_name.partition("/")
    return RepositoryRef(
        github_repo_id=int(evidence.get("github_repo_id") or 0) or _synthetic_id(full_name),
        owner=owner,
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
    )


def _synthetic_id(full_name: str) -> int:
    import hashlib

    digest = hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16)
