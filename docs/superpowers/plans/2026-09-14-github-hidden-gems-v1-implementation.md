# GitHub Hidden Gems V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, low-cost GitHub-native discovery system that finds, scores, remembers, and reports hidden public repositories in AI/agents, automation, data extraction/analysis, and trading.

**Architecture:** A deterministic Python pipeline runs daily in GitHub Actions: discover → filter → light analyze → one-hop relationship expansion → deep static analysis → optional DeepSeek analysis → deterministic scoring → SQLite history → idempotent GitHub Issue publication. External repository content is untrusted and is never executed.

**Tech Stack:** Python 3.11, standard-library `sqlite3`, `httpx`, `PyYAML`, `jsonschema`, `pytest`; GitHub REST API; GitHub Actions; DeepSeek-compatible HTTP API behind a provider interface.

**Spec:** `docs/superpowers/specs/2026-09-14-github-hidden-gems-design.md`

## Global Constraints

- Areas: AI/agents, automation, data extraction/analysis, trading; equal base importance.
- `PRIMARY_STAR_LIMIT = 499`; exception range `500..2000`; >2000 is not notifiable in V1.
- Notification thresholds: normal `>=70`; 500–2000 stars `>=80`; exceptional `>=85`.
- Renotification by score requires `+10` versus the last notified score.
- Normal report maximum 5; absolute maximum 10; positions 6–10 require score `>=85`.
- Relationship depth is exactly 1.
- Maximum initial budgets/run: 1,000 unique seen; 200 light; 20 relationship seeds; 25 deep.
- External repository code must never be executed, installed, imported, built, tested, or run in Docker/notebooks.
- SQLite is canonical history; GitHub Issues are the user-facing archive.
- Initial LLM provider is DeepSeek, but `LLM_ENABLED=false` must remain fully functional.
- Initial schedule is daily; production triggers are `schedule` and `workflow_dispatch` only.
- Use `GITHUB_TOKEN` with minimum permissions; no PAT in V1 unless a documented blocker is demonstrated.
- Unknown configuration keys are fatal before network activity.
- Scoring, selection, fingerprints, and notification decisions must be deterministic for fixed evidence/configuration.
- Production state writes are serialized; no two runs may write `state` concurrently.

---

## File Map

The implementation should create these primary files. Keep modules focused; split further only when a file grows beyond a single responsibility.

```text
.github/workflows/tests.yml
.github/workflows/daily_discovery.yml
config/discovery.yml
config/topics.yml
config/scoring.yml
config/limits.yml
prompts/deep_analyzer_v1.txt
schemas/llm_analysis_v1.json
migrations/sqlite/001_initial.sql
src/hidden_gems/__init__.py
src/hidden_gems/cli.py
src/hidden_gems/orchestrator.py
src/hidden_gems/config.py
src/hidden_gems/models.py
src/hidden_gems/discovery/engine.py
src/hidden_gems/discovery/queries.py
src/hidden_gems/filtering/hard_filter.py
src/hidden_gems/filtering/rules.py
src/hidden_gems/light_analysis/analyzer.py
src/hidden_gems/light_analysis/activity.py
src/hidden_gems/light_analysis/classification.py
src/hidden_gems/relationships/explorer.py
src/hidden_gems/deep_analysis/analyzer.py
src/hidden_gems/deep_analysis/file_selector.py
src/hidden_gems/deep_analysis/evidence_builder.py
src/hidden_gems/scoring/hidden_gem_v1.py
src/hidden_gems/scoring/preliminary.py
src/hidden_gems/history/database.py
src/hidden_gems/history/repository.py
src/hidden_gems/history/integrity.py
src/hidden_gems/reporting/selector.py
src/hidden_gems/reporting/markdown.py
src/hidden_gems/reporting/fingerprints.py
src/hidden_gems/github/client.py
src/hidden_gems/github/search.py
src/hidden_gems/github/repositories.py
src/hidden_gems/github/issues.py
src/hidden_gems/github/rate_limits.py
src/hidden_gems/llm/base.py
src/hidden_gems/llm/deepseek.py
src/hidden_gems/llm/validator.py
src/hidden_gems/security/untrusted_content.py
src/hidden_gems/security/sanitization.py
src/hidden_gems/common/hashing.py
src/hidden_gems/common/time.py
src/hidden_gems/common/logging.py
tests/unit/...
tests/integration/...
tests/fixtures/...
tests/live/...
pyproject.toml
README.md
```

## Canonical Domain Interfaces

These names are fixed for the implementation plan so tasks can be developed independently.

```python
@dataclass(frozen=True)
class RepositoryRef:
    github_repo_id: int
    owner: str
    name: str
    full_name: str
    html_url: str

@dataclass
class DiscoveryCandidate:
    repo: RepositoryRef
    description: str | None
    stars: int
    created_at: datetime
    updated_at: datetime
    primary_language: str | None
    topics: tuple[str, ...]
    discovery_channels: set[str]
    matched_query_ids: set[str]

@dataclass(frozen=True)
class FilterDecision:
    passed: bool
    reason_code: str | None
    evidence: tuple[str, ...]

@dataclass
class LightAnalysis:
    repo: RepositoryRef
    detected_areas: frozenset[str]
    activity_level: str
    quality_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    latest_release_tag: str | None
    latest_release_at: datetime | None
    latest_relevant_activity_at: datetime | None
    readme_hash: str
    tree_hash: str
    dependency_hash: str
    relevant_content_hash: str
    evidence: dict[str, object]

@dataclass
class DeepAnalysis:
    repo: RepositoryRef
    evidence: dict[str, object]
    relevance_suggestion: int | None
    originality_suggestion: int | None
    why_interesting: str | None
    summary: str | None
    risks: tuple[str, ...]
    confidence: str

@dataclass(frozen=True)
class HiddenGemScore:
    relevance: int
    quality: int
    activity: int
    visibility: int
    novelty: int
    originality: int
    intersection: int
    total: int
    confidence: str
    score_version: str = "HIDDEN_GEM_SCORE_V1"

@dataclass(frozen=True)
class NotificationDecision:
    notify: bool
    notification_type: str | None
    trigger_fingerprint: str | None
    previous_score: int | None
    current_score: int

@dataclass
class RunContext:
    run_id: str
    started_at: datetime
    dry_run: bool
    config_version: str
    score_version: str
    prompt_version: str
    budgets: dict[str, int | float]
    usage: dict[str, int | float]
```

---

### Task 1: Bootstrap package, canonical configuration, and domain models

**Files:**
- Create: `pyproject.toml`
- Create: `config/discovery.yml`
- Create: `config/topics.yml`
- Create: `config/scoring.yml`
- Create: `config/limits.yml`
- Create: `src/hidden_gems/config.py`
- Create: `src/hidden_gems/models.py`
- Create: `src/hidden_gems/cli.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `AppConfig`, `load_config(root: Path) -> AppConfig`, `validate_config(config: AppConfig) -> None`, and the canonical dataclasses in the Domain Interfaces section.
- Consumes: nothing from later tasks.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_canonical_scoring_weights_sum_to_100(app_config):
    assert sum(app_config.scoring.weights.values()) == 100


def test_unknown_config_key_is_fatal(tmp_path, canonical_config_tree):
    canonical_config_tree(tmp_path, extra_limits={"max_lmm_calls": 3})
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(tmp_path)


def test_v1_invariants_are_loaded(app_config):
    assert app_config.scoring.notification_threshold == 70
    assert app_config.scoring.exceptional_threshold == 85
    assert app_config.scoring.renotification_score_delta == 10
    assert app_config.discovery.relationship_depth == 1
    assert app_config.reporting.normal_max == 5
    assert app_config.reporting.absolute_max == 10
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `pytest tests/unit/test_config.py -v`  
Expected: FAIL because configuration loader and types do not exist.

- [ ] **Step 3: Add minimal package/dependency metadata**

`pyproject.toml` must declare Python `>=3.11,<3.13`, runtime dependencies `httpx`, `PyYAML`, `jsonschema`, and dev dependency `pytest`. Add console script `hidden-gems = hidden_gems.cli:main`.

- [ ] **Step 4: Implement strict typed configuration loading**

Implement explicit accepted keys for every YAML file. Reject unknown keys, invalid ranges, weights not summing to 100, relationship depth other than 1, `absolute_max > 10`, or `normal_max > absolute_max`. Configuration validation must not make network calls.

- [ ] **Step 5: Create canonical V1 configuration files**

Populate the exact frozen values from the Global Constraints, including preferred languages, age/activity windows, star bands, four equal-interest topic families, thresholds, and initial run budgets.

- [ ] **Step 6: Add CLI validation command**

`hidden-gems validate-config --root .` returns exit 0 and prints `RESULT=CONFIG_VALID`; invalid configuration returns non-zero and `RESULT=FAILED_CONFIGURATION`.

- [ ] **Step 7: Run unit tests**

Run: `pytest tests/unit/test_config.py tests/unit/test_models.py -v`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml config src/hidden_gems/config.py src/hidden_gems/models.py src/hidden_gems/cli.py tests/unit/test_config.py tests/unit/test_models.py
git commit -m "feat: bootstrap hidden gems configuration and domain models"
```

---

### Task 2: SQLite schema, repository layer, transactions, and integrity checks

**Files:**
- Create: `migrations/sqlite/001_initial.sql`
- Create: `src/hidden_gems/history/database.py`
- Create: `src/hidden_gems/history/repository.py`
- Create: `src/hidden_gems/history/integrity.py`
- Test: `tests/unit/history/test_database.py`
- Test: `tests/unit/history/test_repository.py`
- Test: `tests/integration/test_history_transactions.py`

**Interfaces:**
- Consumes: `RepositoryRef`, `HiddenGemScore`, `RunContext`.
- Produces: `HistoryStore.open(path)`, `HistoryStore.transaction()`, `HistoryStore.integrity_check()`, `get_repository()`, `upsert_repository()`, `save_observation()`, `save_score()`, `save_filter_decision()`, `save_discovery_hit()`, `save_llm_analysis()`, `save_notification()`, `find_pending_report()`, `mark_report_published()`, `start_run()`, `finish_run()`.

- [ ] **Step 1: Write schema tests**

Test that all canonical tables exist, foreign keys are ON, `schema_migrations` contains version 1, and a new database returns `ok` from integrity check.

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest tests/unit/history/test_database.py -v`  
Expected: FAIL because history package does not exist.

- [ ] **Step 3: Implement `001_initial.sql`**

Create the tables from SPEC_V1 with primary/foreign keys, unique constraints on GitHub repository IDs and notification fingerprints, indexes on `last_seen_at`, `current_score`, `state`, and `run_id`, plus `schema_migrations`.

- [ ] **Step 4: Implement connection and transaction handling**

Every connection executes `PRAGMA foreign_keys=ON`. `transaction()` must commit on success and rollback on exception. `integrity_check()` must return `True` only when SQLite returns exactly `ok`.

- [ ] **Step 5: Write rollback test**

```python
def test_failed_transaction_does_not_leave_partial_notification(store, repo):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_repository(repo)
            store.save_notification(...)
            raise RuntimeError("forced")
    assert store.get_repository(repo.github_repo_id) is None
```

- [ ] **Step 6: Implement repository methods and canonical run states**

Allowed run results: `SUCCESS`, `SUCCESS_NO_FINDINGS`, `PARTIAL_SUCCESS`, `PARTIAL_SUCCESS_RATE_LIMIT`, `FAILED_INTEGRITY`, `FAILED_CONFIGURATION`.

- [ ] **Step 7: Run history tests**

Run: `pytest tests/unit/history tests/integration/test_history_transactions.py -v`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add migrations/sqlite src/hidden_gems/history tests/unit/history tests/integration/test_history_transactions.py
git commit -m "feat: add canonical sqlite history store"
```

---

### Task 3: Central GitHub REST client with retries and rate-budget zones

**Files:**
- Create: `src/hidden_gems/github/client.py`
- Create: `src/hidden_gems/github/rate_limits.py`
- Create: `src/hidden_gems/github/search.py`
- Create: `src/hidden_gems/github/repositories.py`
- Test: `tests/unit/github/test_client.py`
- Test: `tests/unit/github/test_rate_limits.py`
- Fixture: `tests/fixtures/github/rate_limit.json`

**Interfaces:**
- Produces: `GitHubClient.get_json(path, params=None)`, `search_repositories(query, page)`, `get_repo_metadata(full_name)`, `get_readme(full_name)`, `get_tree(full_name, ref)`, `get_releases(full_name)`, `get_recent_commits(full_name, since)`, `RateBudget.zone -> GREEN|YELLOW|RED`.
- All external GitHub reads must flow through `GitHubClient`.

- [ ] **Step 1: Write retry and redaction tests**

Verify Authorization headers are never included in exception messages/log records, 403/429 responses honor `Retry-After` when present, retries stop at configured maximum, and a 404 returns a normalized `GitHubNotFound`.

- [ ] **Step 2: Write rate-zone tests**

Use fixed fixtures to prove GREEN above the configured yellow floor, YELLOW below it, and RED at/below the red floor. Zone thresholds come from `config/limits.yml`.

- [ ] **Step 3: Run tests and confirm failure**

Run: `pytest tests/unit/github -v`  
Expected: FAIL.

- [ ] **Step 4: Implement the client and normalized errors**

Use `httpx.Client` with explicit connect/read timeouts. Add `Accept: application/vnd.github+json`, API version header, and `Authorization: Bearer <token>` only when token is present. Never interpolate token into URLs.

- [ ] **Step 5: Implement rate-limit accounting**

Read `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and search-resource information when available. Expose a single `RateBudget` object to the orchestrator.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/github -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hidden_gems/github tests/unit/github tests/fixtures/github
git commit -m "feat: add rate-aware github api client"
```

---

### Task 4: Discovery query planner, rotating searches, deduplication, and budgets

**Files:**
- Create: `src/hidden_gems/discovery/queries.py`
- Create: `src/hidden_gems/discovery/engine.py`
- Test: `tests/unit/discovery/test_queries.py`
- Test: `tests/unit/discovery/test_engine.py`
- Fixture: `tests/fixtures/github/search_results.json`

**Interfaces:**
- Consumes: `AppConfig`, `GitHubClient`, `HistoryStore`, `RunContext`.
- Produces: `list[DiscoveryCandidate]` plus persisted discovery hits.

- [ ] **Step 1: Write query-planning tests**

Assert that a canonical run produces queries for all four topic families, new-repository windows, recent-activity windows, star bands, core searches, rotating group for that day, and configured pairwise intersections. Assert that explicit Bitcoin/crypto-only searches are absent.

- [ ] **Step 2: Write deduplication test**

A repository returned by NEW_REPOSITORY, TOPIC_SEARCH, and INTERSECTION_SEARCH must yield one `DiscoveryCandidate` with three channels and three query IDs.

- [ ] **Step 3: Write budget test**

With 1,200 unique fixtures and `max_raw_candidates=1000`, engine returns at most 1,000 unique candidates and records `budget_exhausted=True` in run usage.

- [ ] **Step 4: Implement deterministic rotating-group selection**

Use UTC date modulo number of rotating groups. The same date must produce the same group; no randomness.

- [ ] **Step 5: Implement search execution and early rate-zone behavior**

GREEN runs core + rotating queries; YELLOW skips new rotating/relationship-trigger searches; RED stops new searches and returns accumulated candidates.

- [ ] **Step 6: Run discovery tests**

Run: `pytest tests/unit/discovery -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hidden_gems/discovery tests/unit/discovery tests/fixtures/github/search_results.json
git commit -m "feat: add multi-route github discovery engine"
```

---

### Task 5: Hard Filter with structured reasons and conservative innovation rules

**Files:**
- Create: `src/hidden_gems/filtering/rules.py`
- Create: `src/hidden_gems/filtering/hard_filter.py`
- Test: `tests/unit/filtering/test_hard_filter.py`
- Fixtures: `tests/fixtures/repos/*.json`

**Interfaces:**
- Consumes: `DiscoveryCandidate` and cheap repository metadata.
- Produces: `FilterDecision` with one canonical rejection code or pass.

- [ ] **Step 1: Create fixture cases and failing tests**

Fixtures must cover archived, trivial fork, empty, tutorial, template, demo, spam, irrelevant SSH user-agent false positive, zero-star real project, one-contributor real project, and new real project.

- [ ] **Step 2: Run test and confirm failure**

Run: `pytest tests/unit/filtering/test_hard_filter.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement deterministic obvious-rejection rules**

Archived and trivial forks reject immediately. Empty/project-shell detection uses repository size/tree evidence; do not reject only because stars=0, contributor count=1, or releases=0.

- [ ] **Step 4: Implement evidence-based tutorial/template/demo/spam rules**

Require at least two independent weak signals for semantic categories unless GitHub metadata explicitly marks a template. Examples: tutorial wording + notebook-only/minimal tree; boilerplate wording + template metadata; promotional superlatives + minimal implementation.

- [ ] **Step 5: Implement thematic false-positive protection**

`agent` alone is insufficient. Require at least one topic/description/core-term signal plus README or dependency/tree evidence before treating the repo as relevant.

- [ ] **Step 6: Run filter tests**

Run: `pytest tests/unit/filtering/test_hard_filter.py -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hidden_gems/filtering tests/unit/filtering tests/fixtures/repos
git commit -m "feat: add strict explainable hard filter"
```

---

### Task 6: Light Analyzer — README, tree, releases, manifests, hashes, and activity classification

**Files:**
- Create: `src/hidden_gems/light_analysis/analyzer.py`
- Create: `src/hidden_gems/light_analysis/activity.py`
- Create: `src/hidden_gems/light_analysis/classification.py`
- Create: `src/hidden_gems/common/hashing.py`
- Test: `tests/unit/light_analysis/test_activity.py`
- Test: `tests/integration/test_light_analyzer.py`

**Interfaces:**
- Consumes: `DiscoveryCandidate`, `GitHubClient`, `AppConfig`.
- Produces: `LightAnalysis`.

- [ ] **Step 1: Write activity-classification tests**

Cases: release/new feature within 15 days → STRONG; substantive fixes within 15 → MEDIUM/STRONG according to fixture; relevant activity 16–30 → MEDIUM; README typo/badge/bot-only dependency bump → WEAK; >30 days no real activity → STALE.

- [ ] **Step 2: Write content-hash stability tests**

Same normalized README/tree/manifests must produce identical hashes regardless of API item ordering. A substantive file/tree change must change `relevant_content_hash`.

- [ ] **Step 3: Run tests and confirm failure**

Run: `pytest tests/unit/light_analysis tests/integration/test_light_analyzer.py -v`  
Expected: FAIL.

- [ ] **Step 4: Implement bounded content retrieval**

Fetch README, root/recursive tree subject to configured item limit, latest releases, recent commits, and recognized manifests only. Skip binary extensions and oversized content. Do not clone.

- [ ] **Step 5: Implement area classification**

Return any subset of `{"ai_agents","automation","data","trading"}` based on description/topics/README/dependencies. Require central evidence, not isolated terms.

- [ ] **Step 6: Implement quality and negative signals**

Record evidence for `src`, `tests`, `docs`, examples, install instructions, license, CI, and negative claims/minimal implementation. Do not calculate final score here.

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/light_analysis tests/integration/test_light_analyzer.py -v`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/hidden_gems/light_analysis src/hidden_gems/common/hashing.py tests/unit/light_analysis tests/integration/test_light_analyzer.py
git commit -m "feat: add bounded light repository analysis"
```

---

### Task 7: Deterministic V1 score primitives and preliminary pruning

**Files:**
- Create: `src/hidden_gems/scoring/hidden_gem_v1.py`
- Create: `src/hidden_gems/scoring/preliminary.py`
- Test: `tests/unit/scoring/test_hidden_gem_v1.py`
- Test: `tests/unit/scoring/test_preliminary.py`

**Interfaces:**
- Produces: `score_visibility(stars)`, `score_novelty(age_days)`, `score_activity(activity_evidence)`, `score_quality(light, deep=None)`, `score_intersection(areas)`, `compute_preliminary_score(light, metadata)`, `maximum_possible_score(partial)`, `compute_final_score(light, deep, metadata) -> HiddenGemScore`.

**Implementation-level scoring rules that operationalize SPEC_V1:**
- Visibility: exact frozen bands from SPEC_V1; 1000–1499 → 3, 1500–2000 → 1, >2000 → 0.
- Novelty: exact frozen bands.
- Intersection: exact frozen bands.
- Activity: STRONG+0–15 → 20; MEDIUM+0–15 → 16; STRONG/MEDIUM+16–30 → 12; WEAK recent → 7; STALE → 2; no evidence → 0.
- Quality: implementation 0–6, structure 0–4, docs 0–4, tests 0–3, usability 0–2, license/hygiene 0–1. Each subscore is derived only from recorded evidence keys and capped at its maximum.
- Relevance preliminary: 0–14 from deterministic area evidence; final relevance may be raised up to 20 by validated DeepAnalysis evidence but may never exceed the evidence cap calculated from number/strength of centrally verified areas.
- Originality preliminary: 0; final originality is 0–10 from validated DeepAnalysis, or conservative 0–4 in no-LLM mode based only on concrete differentiated capability evidence.

- [ ] **Step 1: Write exact band tests**

Cover every boundary: stars 24/25/99/100/249/250/499/500/999/1000/1499/1500/2000/2001 and novelty days 15/16/30/31/60/61/90/91/180/181.

- [ ] **Step 2: Write frozen example test**

```python
def test_example_hidden_gem_totals_90():
    score = HiddenGemScore(18, 17, 19, 15, 9, 8, 4, 90, "HIGH")
    assert score.total == 90
```

Also assert each dimension and total are range-checked.

- [ ] **Step 3: Write maximum-possible pruning test**

Known partial 41 + maximum pending 24 must return 65 and `can_reach_notification=False`.

- [ ] **Step 4: Implement score primitives and evidence caps**

Make functions pure: no network, no SQLite, no current-clock access except an explicit `as_of` parameter.

- [ ] **Step 5: Implement popular exception gating helper**

`required_notification_threshold(stars)` returns 70 for <=499, 80 for 500..2000, and `None` for >2000.

- [ ] **Step 6: Run scoring tests**

Run: `pytest tests/unit/scoring -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hidden_gems/scoring tests/unit/scoring
git commit -m "feat: implement deterministic hidden gem score v1"
```

---

### Task 8: One-hop Relationship Explorer

**Files:**
- Create: `src/hidden_gems/relationships/explorer.py`
- Test: `tests/unit/relationships/test_explorer.py`

**Interfaces:**
- Consumes: promising `LightAnalysis` records, GitHub client, history, `max_relationship_seeds=20`, `relationship_depth=1`.
- Produces: additional `DiscoveryCandidate` objects tagged `RELATIONSHIP_EXPLORATION`.

- [ ] **Step 1: Write one-hop depth test**

A → B and B → C fixture must return B only. Any attempt to call explorer recursively must fail validation because depth is fixed at 1.

- [ ] **Step 2: Write source tests**

Cover same owner/organization, README links, recognized dependencies, and explicit related-project links. Ensure ordinary external documentation URLs do not become GitHub candidates.

- [ ] **Step 3: Run and confirm failure**

Run: `pytest tests/unit/relationships/test_explorer.py -v`  
Expected: FAIL.

- [ ] **Step 4: Implement bounded expansion**

Only the top preliminary candidates, up to 20 seeds, expand. Every related candidate re-enters normal dedupe/filter/light-analysis flow; it never jumps directly to deep analysis.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/unit/relationships/test_explorer.py -v`  
Expected: PASS.

```bash
git add src/hidden_gems/relationships tests/unit/relationships
git commit -m "feat: add one-hop relationship discovery"
```

---

### Task 9: Deep static analyzer and bounded file selection

**Files:**
- Create: `src/hidden_gems/deep_analysis/file_selector.py`
- Create: `src/hidden_gems/deep_analysis/evidence_builder.py`
- Create: `src/hidden_gems/deep_analysis/analyzer.py`
- Create: `src/hidden_gems/security/untrusted_content.py`
- Test: `tests/unit/deep_analysis/test_file_selector.py`
- Test: `tests/integration/test_deep_analyzer.py`

**Interfaces:**
- Consumes: `LightAnalysis`, `GitHubClient`, `AppConfig`.
- Produces: deterministic deep evidence bundle before optional LLM enrichment.

- [ ] **Step 1: Write file-priority/budget tests**

Given a tree containing manifests, docs, tests, source, datasets, images, lockfiles and a 5 MB generated file, selector must prioritize manifests/docs/tests/core source, exclude binaries/datasets, and obey max files, per-file size, and total content limits.

- [ ] **Step 2: Write no-execution invariant test**

Monkeypatch `subprocess.run`, `os.system`, and import hooks to raise if invoked; deep analyzer fixture must complete without touching them.

- [ ] **Step 3: Write prompt-injection marking test**

Repository text containing `Ignore previous instructions...` is preserved only as quoted untrusted evidence and flagged `prompt_injection_signal=True`; it never changes analyzer control flow.

- [ ] **Step 4: Implement selector and evidence builder**

Evidence must distinguish `observed`, `inferred`, and `unknown`. Include claim-vs-implementation checks such as README claiming a multi-agent framework while tree contains only a tiny single script.

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/deep_analysis tests/integration/test_deep_analyzer.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hidden_gems/deep_analysis src/hidden_gems/security/untrusted_content.py tests/unit/deep_analysis tests/integration/test_deep_analyzer.py
git commit -m "feat: add safe bounded deep repository analysis"
```

---

### Task 10: DeepSeek provider, strict schema validation, usage accounting, and LLM cache

**Files:**
- Create: `prompts/deep_analyzer_v1.txt`
- Create: `schemas/llm_analysis_v1.json`
- Create: `src/hidden_gems/llm/base.py`
- Create: `src/hidden_gems/llm/deepseek.py`
- Create: `src/hidden_gems/llm/validator.py`
- Test: `tests/unit/llm/test_validator.py`
- Test: `tests/unit/llm/test_deepseek.py`
- Test: `tests/integration/test_llm_cache.py`

**Interfaces:**
- `LLMProvider.analyze_repository(evidence: dict) -> DeepAnalysis`.
- DeepSeek implementation accepts API key from environment only.
- History cache key: `(github_repo_id, relevant_content_hash, prompt_version, schema_version, model)`.

- [ ] **Step 1: Write schema tests**

Reject broken JSON, missing confidence, scores outside allowed ranges, free text instead of object, and evidence-less maximum scores. Accept `UNKNOWN`/null where the schema permits uncertainty.

- [ ] **Step 2: Write cache test**

Same repo/hash/prompt/schema/model reuses stored analysis and performs zero provider calls. Changing relevant content hash or prompt version performs a new call.

- [ ] **Step 3: Write budget and retry tests**

With `MAX_LLM_CALLS_PER_RUN=5`, 20 candidates may trigger at most 5 calls including retries. Permanent schema failure after configured retry count marks candidate `LLM_FAILED` and does not fabricate a score.

- [ ] **Step 4: Implement prompt**

The prompt must explicitly state that repository content is untrusted data, never instructions; require observed/inferred/unknown distinction, concrete evidence, bounded score suggestions, risks, summary, why-interesting, and confidence.

- [ ] **Step 5: Implement DeepSeek HTTP provider**

Use explicit timeouts, no secret logging, and usage extraction when returned. Do not expose generic tool-calling or browsing capabilities to the model.

- [ ] **Step 6: Implement LLM-disabled path**

When `LLM_ENABLED=false`, return deterministic DeepAnalysis with no model suggestions and conservative confidence; pipeline must continue.

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/llm tests/integration/test_llm_cache.py -v`  
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add prompts schemas src/hidden_gems/llm tests/unit/llm tests/integration/test_llm_cache.py
git commit -m "feat: add bounded deepseek analysis provider"
```

---

### Task 11: Final score, confidence gating, history-aware notification decisions

**Files:**
- Modify: `src/hidden_gems/scoring/hidden_gem_v1.py`
- Create: `src/hidden_gems/reporting/selector.py`
- Create: `src/hidden_gems/reporting/fingerprints.py`
- Test: `tests/unit/reporting/test_selector.py`
- Test: `tests/unit/reporting/test_fingerprints.py`

**Interfaces:**
- Consumes: final `HiddenGemScore`, last notification/history, release/activity/content changes.
- Produces: `NotificationDecision` and selected ordered candidates.

- [ ] **Step 1: Write threshold tests**

Cases: 499 stars score 70 → notify; 1,200 stars score 79 → no; 1,200 stars score 80 → notify; 2,001 stars score 100 → no; confidence LOW → no immediate notification.

- [ ] **Step 2: Write renotification tests**

72→79 no, 72→81 no (+9), 72→82 yes (+10). Compare against last *notified* score, not previous daily score. New major release can produce an update if current score still meets threshold. Identical release fingerprint must never notify twice.

- [ ] **Step 3: Write 5/10 selection tests**

Eight candidates 70–84 → top five only. Five normal plus three >=85 → eight. More than ten exceptional → top ten. No candidate → empty selection.

- [ ] **Step 4: Implement deterministic fingerprints**

Examples: `FIRST_DISCOVERY:<repo_id>:<score_version>`, `NEW_RELEASE:<repo_id>:<release_id>`, `SCORE_INCREASE:<repo_id>:<last_notification_id>:<current_score>`, `MAJOR_CHANGE:<repo_id>:<relevant_content_hash>`.

- [ ] **Step 5: Implement selector and confidence gate**

Ordering: total score, confidence rank HIGH>MEDIUM>LOW, novelty points, visibility points, activity points, repo ID as final deterministic tie-breaker.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/unit/reporting -v`  
Expected: PASS.

```bash
git add src/hidden_gems/scoring/hidden_gem_v1.py src/hidden_gems/reporting tests/unit/reporting
git commit -m "feat: add history-aware notification selection"
```

---

### Task 12: Markdown report generation, sanitization, GitHub Issue publishing, and idempotency

**Files:**
- Create: `src/hidden_gems/reporting/markdown.py`
- Create: `src/hidden_gems/security/sanitization.py`
- Create: `src/hidden_gems/github/issues.py`
- Test: `tests/unit/reporting/test_markdown.py`
- Test: `tests/integration/test_issue_idempotency.py`

**Interfaces:**
- `build_report(candidates, run_summary) -> str`.
- `GitHubIssuePublisher.find_by_fingerprint(fingerprint) -> IssueRef | None`.
- `GitHubIssuePublisher.publish(report, fingerprint, labels, assignee) -> IssueRef`.

- [ ] **Step 1: Write report-content tests**

Each project must include exactly the required user fields plus confidence and NEW/UPDATE status. Exceptional entries show EXCEPTIONAL. Updates show previous/current/delta when applicable. Zero candidates yields no report object.

- [ ] **Step 2: Write sanitization test**

External HTML/script tags, extremely long descriptions, control characters, and prompt-injection text must not be emitted raw into the Issue. Repository links must be canonical `https://github.com/<owner>/<repo>` URLs built from validated owner/name.

- [ ] **Step 3: Write two-phase idempotency integration test**

Simulate: pending report persisted → Issue created → crash before final SQLite confirmation. On rerun, publisher finds `REPORT_FINGERPRINT`, adopts existing Issue, and total created Issues remains 1.

- [ ] **Step 4: Implement Markdown renderer and labels**

All reports get `discovery-report`; any >=85 adds `exceptional-findings`; any update adds `has-updates`. Include RUN_ID, SCORE_VERSION, and REPORT_FINGERPRINT in a compact footer/comment marker.

- [ ] **Step 5: Implement GitHub Issue publisher**

Create/adopt issue using the central GitHub client; assign `NOTIFICATION_GITHUB_LOGIN` when configured. The publisher is the only code path allowed to POST Issues.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/unit/reporting/test_markdown.py tests/integration/test_issue_idempotency.py -v`  
Expected: PASS.

```bash
git add src/hidden_gems/reporting/markdown.py src/hidden_gems/security/sanitization.py src/hidden_gems/github/issues.py tests/unit/reporting/test_markdown.py tests/integration/test_issue_idempotency.py
git commit -m "feat: add idempotent github issue reporting"
```

---

### Task 13: Orchestrator, dry-run, fail-soft behavior, and run summaries

**Files:**
- Create: `src/hidden_gems/orchestrator.py`
- Modify: `src/hidden_gems/cli.py`
- Create: `src/hidden_gems/common/logging.py`
- Test: `tests/integration/test_pipeline_dry_run.py`
- Test: `tests/integration/test_pipeline_fail_soft.py`

**Interfaces:**
- `run_pipeline(config: AppConfig, history: HistoryStore, github: GitHubClient, llm: LLMProvider | None, context: RunContext) -> RunSummary`.
- CLI: `hidden-gems run [--dry-run]`, `hidden-gems db-check`, `hidden-gems migrate`, `hidden-gems validate-config`.

- [ ] **Step 1: Write end-to-end dry-run fixture test**

Use fake GitHub + fake LLM + temporary SQLite. Verify discovery → filter → light → relation → deep → score → selection → report completes, persists run evidence in temp DB, and makes zero Issue POSTs when dry-run.

- [ ] **Step 2: Write fail-soft test**

Four candidates: A OK, B 404, C timeout, D OK. A/D finish; B/C errors are recorded; run result is `PARTIAL_SUCCESS`, not total failure.

- [ ] **Step 3: Write rate-limit stop test**

When budget changes to RED after discovery, stop new GitHub work, persist valid accumulated state, and finish `PARTIAL_SUCCESS_RATE_LIMIT`.

- [ ] **Step 4: Implement orchestrator with explicit phase boundaries**

No phase reaches into another module's side effects. Validate config before network. Validate SQLite before final state publication. Log only summary counts, RUN_ID, result, budgets, and redacted error types.

- [ ] **Step 5: Implement CLI results**

Every run prints one terminal `RESULT=<STATE>` line. `SUCCESS_NO_FINDINGS` is exit 0. Integrity/configuration failures are non-zero.

- [ ] **Step 6: Run integration suite and commit**

Run: `pytest tests/integration/test_pipeline_dry_run.py tests/integration/test_pipeline_fail_soft.py -v`  
Expected: PASS.

```bash
git add src/hidden_gems/orchestrator.py src/hidden_gems/cli.py src/hidden_gems/common/logging.py tests/integration/test_pipeline_*.py
git commit -m "feat: orchestrate safe end-to-end discovery runs"
```

---

### Task 14: State-branch checkpoint/publish protocol and backup rotation

**Files:**
- Create: `src/hidden_gems/history/state_branch.py`
- Test: `tests/integration/test_state_branch_protocol.py`
- Create: `state_manifest.schema.json`

**Interfaces:**
- `StateBranchManager.load(workdir) -> StateSnapshot`.
- `checkpoint_pending_report(snapshot, report_fingerprint) -> None`.
- `persist(snapshot, expected_parent_sha) -> new_sha`.
- `rotate_backups(max_backups)`.

- [ ] **Step 1: Write atomic-state tests using a temporary git repository**

Initialize local `main` and `state` branches. Verify a valid DB can be loaded and persisted; failed integrity check leaves the prior `state` commit unchanged.

- [ ] **Step 2: Write optimistic-parent test**

If state branch HEAD changed after load, persistence must fail with `StateConflict` rather than overwrite concurrent state.

- [ ] **Step 3: Write backup-rotation test**

Given `max_backups=3`, four successful snapshots leave exactly three compressed backups plus current DB and manifest.

- [ ] **Step 4: Implement state manager**

Use git operations only on the project’s own repository. Never store secrets. Manifest records DB SHA256, schema version, last run ID, state timestamp, and report state.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/integration/test_state_branch_protocol.py -v`  
Expected: PASS.

```bash
git add src/hidden_gems/history/state_branch.py tests/integration/test_state_branch_protocol.py state_manifest.schema.json
git commit -m "feat: add atomic state branch persistence"
```

---

### Task 15: GitHub Actions workflows with minimum permissions and concurrency

**Files:**
- Create: `.github/workflows/tests.yml`
- Create: `.github/workflows/daily_discovery.yml`
- Test: `tests/unit/test_workflow_contracts.py`

**Interfaces:**
- Test workflow: no production DeepSeek secret; runs config/schema/unit/integration tests.
- Production workflow: `schedule` + `workflow_dispatch`; one concurrency group; minimum permissions; checks out `main`, loads `state`, runs pipeline, persists state.

- [ ] **Step 1: Write workflow contract tests**

Parse workflow YAML and assert: no `pull_request_target`; production triggers contain only schedule/workflow_dispatch; concurrency group exists; default permissions are read-only; only publishing/state jobs request `issues: write` or `contents: write`; no PAT secret is referenced.

- [ ] **Step 2: Create `tests.yml`**

Use Ubuntu, Python 3.11, dependency install from `pyproject.toml`, run `hidden-gems validate-config`, unit tests, integration tests, and JSON schema checks. No live tests.

- [ ] **Step 3: Create `daily_discovery.yml`**

Schedule once daily at a non-round UTC minute. Use `GITHUB_TOKEN`; map only `DEEPSEEK_API_KEY` from Actions Secrets. Configure `concurrency: hidden-gems-state-writer` with safe serialization. Add explicit timeout-minutes.

- [ ] **Step 4: Add dry-run input to manual dispatch**

`workflow_dispatch.inputs.dry_run` boolean defaults true for manual launches until controlled-live approval. Scheduled runs use production value from configuration after deployment gate is opened.

- [ ] **Step 5: Run workflow contract tests**

Run: `pytest tests/unit/test_workflow_contracts.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows tests/unit/test_workflow_contracts.py
git commit -m "ci: add constrained test and daily discovery workflows"
```

---

### Task 16: Reference corpus, acceptance metrics, and controlled-live commands

**Files:**
- Create: `tests/fixtures/reference_corpus/manifest.yml`
- Create: `tests/integration/test_reference_corpus.py`
- Create: `tests/live/test_github_contract.py`
- Create: `docs/operations.md`
- Modify: `README.md`

**Interfaces:**
- Reference corpus contains 20–40 frozen cases labeled GOOD/MAYBE/BAD and rationale.
- Live tests are opt-in and read-only unless explicit controlled-publication flag is set.

- [ ] **Step 1: Create reference-corpus schema and test harness**

Each entry includes fixture path, expected class, expected hard-filter outcome where deterministic, and acceptable score band rather than one exact score when semantic judgment is involved.

- [ ] **Step 2: Add mandatory adversarial cases**

Include trivial marketing-heavy repo, zero-star high-quality new repo, tutorial, template, old reactivated repo, >2,000-star excellent repo, prompt-injection README, and duplicate multi-query repo.

- [ ] **Step 3: Add Useful Discovery Rate calculation**

For fixture evaluation, `(GOOD + MAYBE notified) / all notified` must be reported. Acceptance floor is 70%; EXCEPTIONAL false positive is reported separately as a critical calibration warning.

- [ ] **Step 4: Add read-only live GitHub contract test**

With `RUN_LIVE_TESTS=1`, query a very small configured set (10–30 max), create no Issue, use no LLM by default, and verify API parsing/rate-limit headers.

- [ ] **Step 5: Write operations documentation**

Document secrets, `Watch → Custom → Issues`, notification email setting, `NOTIFICATION_GITHUB_LOGIN`, budget/overage protection, manual dry-run, DB check, recovery from `PENDING_REPORT`, and how to disable LLM.

- [ ] **Step 6: Run non-live acceptance tests**

Run: `pytest tests/integration/test_reference_corpus.py -v`  
Expected: PASS and print Useful Discovery Rate.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/reference_corpus tests/integration/test_reference_corpus.py tests/live/test_github_contract.py docs/operations.md README.md
git commit -m "test: add v1 acceptance corpus and operations guide"
```

---

### Task 17: Controlled Live Test gate

**Files:**
- Modify only if defects are found in files owned by earlier tasks.
- Record evidence: `docs/validation/controlled-live-YYYYMMDD.md`

**Interfaces:**
- Consumes a configured private GitHub repository, `DEEPSEEK_API_KEY`, GitHub notification settings, and the V1 codebase.
- Produces a signed-off controlled-live evidence report; does not yet declare V1_ACCEPTED.

- [ ] **Step 1: Run full offline suite**

Run: `pytest -m "not live" -v`  
Expected: PASS.

- [ ] **Step 2: Run configuration and DB checks**

Run: `hidden-gems validate-config --root .` → `RESULT=CONFIG_VALID`.  
Run: `hidden-gems db-check` → `RESULT=DB_VALID`.

- [ ] **Step 3: Run a small live read-only dry-run**

Use limits lower than production: at most 30 unique seen, 10 light, 3 deep, 1–2 LLM calls. Expected: no Issue created, API budget remains healthy, no secret appears in logs.

- [ ] **Step 4: Inspect candidate quality manually**

Verify at least one trace from discovery query → filter → evidence → score can be reconstructed from SQLite/log summaries.

- [ ] **Step 5: Run one controlled publication**

Only if at least one real candidate meets threshold. Create one Issue through the production publisher, verify its fingerprint, labels, assignment, SQLite notification row, and email delivery. If no real candidate meets threshold, use a dedicated repository-owned synthetic publication fixture clearly labeled TEST and delete/close it after verifying transport; never lower the production score threshold.

- [ ] **Step 6: Test idempotent re-run**

Re-run the same publication state; expected: no duplicate Issue.

- [ ] **Step 7: Record evidence and commit**

Document run IDs, limits, result states, API usage, LLM usage/cost, Issue number if created, email verification result, and any defects fixed.

```bash
git add docs/validation/controlled-live-*.md
git commit -m "docs: record controlled live validation"
```

---

### Task 18: Seven-cycle operational validation and V1 acceptance gate

**Files:**
- Create: `docs/validation/v1-acceptance.md`
- Modify code/config only through separately reviewed fixes if validation reveals defects.

**Interfaces:**
- Produces final status: `LIVE_VALIDATED` then `V1_ACCEPTED` only if all acceptance criteria pass.

- [ ] **Step 1: Run seven scheduled daily cycles**

Do not manually fill missing days. Each run must end with an explicit result state and persisted SQLite integrity check.

- [ ] **Step 2: Verify hard safety criteria across all seven cycles**

Required: 0 SQLite corruption, 0 exposed secrets, 0 duplicate Issues, 0 concurrent state conflicts that overwrite data, 0 budget overruns.

- [ ] **Step 3: Calculate operational metrics**

Report Actions minutes/run, GitHub API calls/run, candidates per stage, LLM calls/tokens/cost, cache hits, number of Issues, number of notifications, and projected monthly cost.

- [ ] **Step 4: Grade every notified repository**

Mark each GOOD/MAYBE/BAD. Calculate Useful Discovery Rate. Required floor: `>=70% GOOD+MAYBE`. Review every >=85 result individually; an obviously mediocre exceptional result blocks acceptance pending recalibration.

- [ ] **Step 5: Verify silent-day behavior**

Any day with zero qualifying candidates must have `SUCCESS_NO_FINDINGS` and no Issue.

- [ ] **Step 6: Write acceptance report**

`docs/validation/v1-acceptance.md` must record each criterion as PASS/FAIL with evidence and finish with exactly one of `STATUS=V1_ACCEPTED` or `STATUS=V1_NOT_ACCEPTED`.

- [ ] **Step 7: Commit acceptance evidence**

```bash
git add docs/validation/v1-acceptance.md
git commit -m "docs: record hidden gems v1 acceptance"
```

---

## Plan Self-Review

### Spec coverage

- Discovery routes, star bands, temporal windows, rotating searches: Tasks 4, 8.
- Strict filter and low-noise philosophy: Task 5.
- Light/deep progressive analysis and no external execution: Tasks 6, 9.
- Hidden Gem Score V1, 70/80/85 thresholds, +10 renotification: Tasks 7, 11.
- DeepSeek optional/provider boundary, prompt-injection defense, token limits/cache: Tasks 9, 10.
- SQLite history, hashes, releases, notifications, runs: Tasks 2, 10, 14.
- GitHub Issue archive, 5/10 rule, idempotency, email-supporting assignment: Tasks 11, 12, 17.
- `main`/`state` persistence and integrity: Tasks 2, 14, 15.
- Permissions, concurrency, schedules, cost controls: Tasks 3, 13, 15.
- Dry-run, reference corpus, controlled live and seven-cycle validation: Tasks 13, 16, 17, 18.

### Type consistency

All task interfaces use the canonical domain types defined at the top of this plan. Provider, history, scoring, reporting and orchestration boundaries do not bypass their owning modules.

### Placeholder scan

The plan contains no forbidden placeholder markers or unspecified test steps. Values not frozen by SPEC_V1 are defined here as implementation-level rules, particularly the exact deterministic activity mapping, the 1,000–2,000-star visibility split, and the evidence-capped relevance/originality mechanics.
