"""Task 10: LLM cache reuse keyed by content, prompt, schema and model."""

from __future__ import annotations

from dataclasses import replace

from hidden_gems.llm.base import DisabledLLMProvider
from hidden_gems.llm.cache import CachedLLMProvider
from hidden_gems.models import DeepAnalysis, RepositoryRef


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_repository(self, evidence) -> DeepAnalysis:
        self.calls += 1
        return DeepAnalysis(
            repo=RepositoryRef.from_full_name("acme-labs/flowkit", 501),
            evidence={"observed": []},
            relevance_suggestion=10,
            originality_suggestion=2,
            why_interesting="Compact",
            summary="A small runtime",
            confidence="MEDIUM",
            status="OK",
        )


class FakeStore:
    """Double for HistoryStore's LLM-analysis cache methods (Task 2 owns it)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, DeepAnalysis] = {}
        self.saved: list[tuple] = []

    @staticmethod
    def key(repo_id, content_hash, prompt_version, schema_version, model):
        return (repo_id, content_hash, prompt_version, schema_version, model)

    def find_llm_analysis(self, *, github_repo_id, relevant_content_hash, prompt_version,
                          schema_version, model):
        return self.rows.get(
            self.key(github_repo_id, relevant_content_hash, prompt_version, schema_version, model)
        )

    def save_llm_analysis(self, github_repo_id, *, run_id, analyzed_at, relevant_content_hash,
                          prompt_version, schema_version, model, analysis, input_tokens=0,
                          output_tokens=0, cost=0.0) -> None:
        self.rows[
            self.key(github_repo_id, relevant_content_hash, prompt_version, schema_version, model)
        ] = analysis
        self.saved.append(
            (github_repo_id, relevant_content_hash, prompt_version, schema_version, model)
        )


def evidence(content_hash: str = "hash-1") -> dict:
    return {
        "repo": "acme-labs/flowkit",
        "github_repo_id": 501,
        "relevant_content_hash": content_hash,
        "repository": {
            "full_name": "acme-labs/flowkit",
            "github_repo_id": 501,
            "html_url": "https://github.com/acme-labs/flowkit",
        },
    }


def test_second_identical_request_performs_zero_provider_calls(app_config):
    store = FakeStore()
    provider = CountingProvider()
    cached = CachedLLMProvider(provider, store, run_id="RUN-1", model=app_config.llm.model)

    first = cached.analyze_repository(evidence())
    second = cached.analyze_repository(evidence())

    assert provider.calls == 1
    assert len(store.saved) == 1
    assert first.source == "PROVIDER"
    assert second.source == "CACHE"


def test_changed_content_hash_performs_a_new_call(app_config):
    store = FakeStore()
    provider = CountingProvider()
    cached = CachedLLMProvider(provider, store, run_id="RUN-1", model=app_config.llm.model)

    cached.analyze_repository(evidence("hash-1"))
    cached.analyze_repository(evidence("hash-2"))

    assert provider.calls == 2


def test_changed_prompt_version_performs_a_new_call(app_config):
    store = FakeStore()
    provider = CountingProvider()
    base = CachedLLMProvider(provider, store, run_id="RUN-1", model=app_config.llm.model)
    bumped = CachedLLMProvider(
        provider,
        store,
        run_id="RUN-1",
        model=app_config.llm.model,
        prompt_version="DEEP_ANALYZER_PROMPT_V2",
    )

    base.analyze_repository(evidence())
    bumped.analyze_repository(evidence())

    assert provider.calls == 2


def test_changed_model_performs_a_new_call(app_config):
    store = FakeStore()
    provider = CountingProvider()
    first = CachedLLMProvider(provider, store, run_id="RUN-1", model="deepseek-chat")
    second = CachedLLMProvider(provider, store, run_id="RUN-1", model="deepseek-reasoner")

    first.analyze_repository(evidence())
    second.analyze_repository(evidence())

    assert provider.calls == 2


def test_failed_analyses_are_not_cached(app_config):
    store = FakeStore()
    provider = CountingProvider()
    provider.analyze_repository = lambda ev: replace(
        DisabledLLMProvider().analyze_repository(ev), status="LLM_FAILED"
    )
    cached = CachedLLMProvider(provider, store, run_id="RUN-1", model=app_config.llm.model)

    cached.analyze_repository(evidence())

    assert store.saved == []


def test_disabled_provider_keeps_the_pipeline_alive(app_config):
    deep = DisabledLLMProvider().analyze_repository(evidence())

    assert deep.status == "OK"
    assert deep.source == "DISABLED"
    assert deep.relevance_suggestion is None
    assert deep.confidence == "LOW"
