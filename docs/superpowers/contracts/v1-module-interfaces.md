# GitHub Hidden Gems V1 — Frozen Module Interfaces

Status: FROZEN for SPEC_V1 implementation. These signatures are the contract
between modules so that tasks can be implemented independently. Implementers
may add private helpers; they must not change these names or signatures
without a recorded ruling from the plan owner.

Domain models live in `src/hidden_gems/models.py` and are canonical:
`RepositoryRef`, `DiscoveryCandidate`, `FilterDecision`, `LightAnalysis`,
`DeepAnalysis`, `HiddenGemScore`, `PreliminaryScore`, `MaximumPossibleScore`,
`NotificationDecision`, `IssueRef`, `SelectedFinding`, `RunContext`,
`RunSummary`.

Configuration lives in `src/hidden_gems/config.py` (`load_config(root)`,
`validate_config(config)`, `AppConfig` and its sections).

## Canonical vocabulary

Discovery channels: `NEW_REPOSITORY`, `RECENT_ACTIVITY`, `TOPIC_SEARCH`,
`INTERSECTION_SEARCH`, `RELATIONSHIP_EXPLORATION`.

Filter reason codes: `REJECT_FORK`, `REJECT_ARCHIVED`, `REJECT_EMPTY`,
`REJECT_TUTORIAL`, `REJECT_TEMPLATE`, `REJECT_DEMO`, `REJECT_SPAM`,
`REJECT_IRRELEVANT`, `REJECT_LOW_MAX_SCORE`.

Rate zones: `GREEN`, `YELLOW`, `RED`. Run results: the values of
`models.RUN_RESULTS`.

## `hidden_gems.github`

`client.py`

```python
class GitHubError(Exception):
    status_code: int | None
    endpoint: str | None
class GitHubNotFound(GitHubError): ...
class GitHubAuthError(GitHubError): ...
class GitHubRateLimited(GitHubError):
    retry_after: float | None
class GitHubServerError(GitHubError): ...

class RateBudget:
    zone: str                      # GREEN | YELLOW | RED
    remaining: int | None
    limit: int | None
    reset_at: datetime | None
    search_remaining: int | None
    def update_from_headers(self, headers: Mapping[str, str]) -> None: ...
    def snapshot(self) -> dict[str, object]: ...

class GitHubClient:
    def __init__(self, config, token: str | None = None, *,
                 transport=None, sleep=None, clock=None) -> None: ...
    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any: ...
    def post_json(self, path: str, payload: Mapping[str, Any]) -> Any: ...
    def search_repositories(self, query: str, page: int = 1) -> dict[str, Any]: ...
    def get_repo_metadata(self, full_name: str) -> dict[str, Any]: ...
    def get_readme(self, full_name: str) -> str | None: ...
    def get_tree(self, full_name: str, ref: str) -> list[dict[str, Any]]: ...
    def get_releases(self, full_name: str, limit: int = 10) -> list[dict[str, Any]]: ...
    def get_recent_commits(self, full_name: str, since: datetime | str | None = None,
                           limit: int = 20) -> list[dict[str, Any]]: ...
    @property
    def rate_budget(self) -> RateBudget: ...
    def close(self) -> None: ...
```

Rules: `get_json`/`post_json` return decoded JSON; errors are normalized;
Authorization headers are never included in messages or logs; retries stop at
`github.max_retries` and honor `Retry-After`; 404 raises `GitHubNotFound`;
401/403 auth raises `GitHubAuthError`; 429/403-with-retry-after raises
`GitHubRateLimited`. `search_repositories` returns
`{"total_count": int, "items": [...]}` with `items` as raw GitHub repo JSON.

`repository.py`-level normalization lives in `github/repositories.py`:

```python
def normalize_repo(payload: Mapping[str, Any]) -> RepositoryRecord   # dataclass or dict
def payload_to_candidate(payload: Mapping[str, Any], *, channels: set[str] = ...,
                         query_ids: set[str] = ...) -> DiscoveryCandidate | None: ...
```

Normalized repository fields (dict keys): `github_repo_id`, `owner`, `name`,
`full_name`, `html_url`, `description`, `stars`, `created_at`, `updated_at`,
`pushed_at`, `primary_language`, `topics`, `is_fork`, `is_archived`,
`is_template`, `size_kb`, `default_branch`, `license_spdx_id`, `open_issues`.

## `hidden_gems.discovery`

`queries.py`

```python
@dataclass(frozen=True)
class DiscoveryQuery:
    id: str
    channel: str
    query: str
    template: str
    areas: tuple[str, ...]

@dataclass(frozen=True)
class QueryPlan:
    core: tuple[DiscoveryQuery, ...]
    rotating: tuple[DiscoveryQuery, ...]
    rotating_group_id: str
    as_of_date: date

def build_query_plan(config: AppConfig, as_of: date) -> QueryPlan: ...
```

`engine.py`

```python
@dataclass
class DiscoveryResult:
    candidates: list[DiscoveryCandidate]
    queries_executed: int
    results_seen: int
    budget_exhausted: bool
    stopped_reason: str | None
    rate_zone: str

def run_discovery(config: AppConfig, client: GitHubClient, *,
                  as_of: date, max_candidates: int | None = None,
                  seed_candidates: Sequence[DiscoveryCandidate] = ()) -> DiscoveryResult: ...
```

`seed_candidates` lets later tasks (relationship exploration) merge extra
candidates through the same dedupe path.

## `hidden_gems.filtering`

```python
@dataclass(frozen=True)
class FilterEvidence:
    readme_text: str | None = None
    tree_paths: tuple[str, ...] = ()
    manifest_names: tuple[str, ...] = ()
    commit_messages: tuple[str, ...] = ()
    total_size_kb: int | None = None

def evaluate_candidate(candidate: DiscoveryCandidate,
                       evidence: FilterEvidence | None = None, *,
                       config: AppConfig | None = None) -> FilterDecision: ...
def is_irrelevant(candidate: DiscoveryCandidate,
                  evidence: FilterEvidence | None = None, *,
                  config: AppConfig | None = None) -> bool: ...
```

Semantic rejections (`REJECT_TUTORIAL`, `REJECT_TEMPLATE`, `REJECT_DEMO`,
`REJECT_SPAM`) require at least two independent weak signals, except when
GitHub metadata explicitly marks a template. `REJECT_IRRELEVANT` requires
thematic evidence absence (no area topic/keyword/core-term signal) **and** no
README/dependency/tree evidence. Stars=0, one contributor, no releases, an
unknown author, a non-priority language or extreme youth are never automatic
rejections.

## `hidden_gems.light_analysis`

```python
class LightAnalyzer:
    def __init__(self, config: AppConfig, client: GitHubClient) -> None: ...
    def analyze(self, candidate: DiscoveryCandidate, *, as_of: datetime) -> LightAnalysis: ...

# activity.py
def classify_activity(*, commits: Sequence[Mapping[str, Any]],
                      releases: Sequence[Mapping[str, Any]],
                      relevant_activity_at: datetime | None,
                      as_of: datetime) -> tuple[str, dict[str, Any]]: ...

# classification.py
def detect_areas(*, description: str | None, topics: Sequence[str],
                 readme_text: str | None,
                 dependency_names: Sequence[str],
                 manifest_names: Sequence[str] = ()) -> frozenset[str]: ...
def quality_signals(*, tree_paths: Sequence[str], readme_text: str | None,
                    has_license: bool, has_ci: bool,
                    manifest_names: Sequence[str] = ()) -> tuple[str, ...]: ...
def negative_signals(*, tree_paths: Sequence[str], readme_text: str | None,
                     description: str | None) -> tuple[str, ...]: ...
```

Activity levels: `STRONG`, `MEDIUM`, `WEAK`, `STALE`, `UNKNOWN`.
Releases: README/tree/release/commit reads only; never clone, never execute.

## `hidden_gems.relationships`

```python
@dataclass(frozen=True)
class RelationshipSource:
    source_type: str            # same_owner | readme_link | dependency | related_project_link
    source_repo_id: int

def explore_relationships(*, config: AppConfig, client: GitHubClient,
                          seeds: Sequence[LightAnalysis],
                          existing_repo_ids: Collection[int]) -> list[DiscoveryCandidate]: ...
```

Depth is exactly 1; `explore_relationships` must raise `ValueError` when
`config.discovery.relationship_depth != 1`. Non-GitHub external URLs are never
converted into candidates. Every produced candidate carries
`discovery_channels == {"RELATIONSHIP_EXPLORATION"}` (plus any other channel it
already belonged to).

## `hidden_gems.deep_analysis`

```python
# file_selector.py
@dataclass(frozen=True)
class SelectedFile:
    path: str
    category: str          # manifest | docs | test | source | example | config
    reason: str
    size: int

def select_files(tree_entries: Sequence[Mapping[str, Any]], *,
                 config: AppConfig) -> list[SelectedFile]: ...

# evidence_builder.py
def build_evidence(*, repo: RepositoryRef, light: LightAnalysis,
                   files: Sequence[tuple[SelectedFile, str]],
                   config: AppConfig) -> dict[str, Any]: ...

# analyzer.py
class DeepAnalyzer:
    def __init__(self, config: AppConfig, client: GitHubClient) -> None: ...
    def analyze(self, light: LightAnalysis) -> DeepAnalysis: ...
```

Evidence distinguishes `observed`, `inferred` and `unknown`; includes
claim-vs-implementation checks; flags `prompt_injection_signal` when external
text contains instruction-like content (which is preserved only as quoted
untrusted evidence). External code is never executed, imported, installed,
built or run.

## `hidden_gems.llm`

```python
# base.py
class LLMProvider(Protocol):
    def analyze_repository(self, evidence: dict[str, Any]) -> DeepAnalysis: ...

class DisabledLLMProvider:
    def analyze_repository(self, evidence: dict[str, Any]) -> DeepAnalysis: ...

# deepseek.py
class DeepSeekProvider:
    def __init__(self, config: AppConfig, *, api_key: str | None = None,
                 client=None) -> None: ...
    def analyze_repository(self, evidence: dict[str, Any]) -> DeepAnalysis: ...

# validator.py
PROMPT_VERSION = "DEEP_ANALYZER_PROMPT_V1"
SCHEMA_VERSION = "LLM_ANALYSIS_V1"
def validate_llm_output(payload: Any, *, schema_path: Path | None = None) -> dict[str, Any]: ...
def to_deep_analysis(repo: RepositoryRef, payload: Mapping[str, Any]) -> DeepAnalysis: ...
```

API key comes only from the configured environment variable, never from
arguments persisted anywhere and never from user config secrets. Usage
(tokens, cost) is accounted per run. Second calls are allowed only for invalid
output, a relevant contradiction, a near-exceptional candidate, or a
resolvable-confidence case, and never beyond `max_llm_calls_per_run`.

## `hidden_gems.scoring`

```python
# hidden_gem_v1.py
PRIMARY_STAR_LIMIT = 499
EXCEPTION_STAR_MIN = 500
EXCEPTION_STAR_MAX = 2000
NOTIFICATION_THRESHOLD = 70
EXCEPTION_STAR_THRESHOLD = 80
EXCEPTIONAL_THRESHOLD = 85
RENOTIFICATION_SCORE_DELTA = 10

def score_visibility(stars: int, *, config: ScoringConfig | None = None) -> int: ...
def score_novelty(age_days: int, *, config: ScoringConfig | None = None) -> int: ...
def score_activity(activity_level: str, relevant_activity_age_days: int | None, *,
                   config: ScoringConfig | None = None) -> int: ...
def score_quality(quality_signals: Sequence[str],
                  negative_signals: Sequence[str] = (), *,
                  deep: DeepAnalysis | None = None,
                  config: ScoringConfig | None = None) -> int: ...
def score_intersection(areas: Collection[str], *, config: ScoringConfig | None = None) -> int: ...
def required_notification_threshold(stars: int, *, config: ScoringConfig | None = None) -> int | None: ...

# preliminary.py
def compute_preliminary_score(light: LightAnalysis, metadata: Mapping[str, Any]) -> PreliminaryScore: ...
def maximum_possible_score(partial: PreliminaryScore, *,
                           notification_threshold: int = NOTIFICATION_THRESHOLD) -> MaximumPossibleScore: ...
def compute_final_score(light: LightAnalysis, deep: DeepAnalysis | None,
                        metadata: Mapping[str, Any], *,
                        config: AppConfig | None = None,
                        as_of: datetime | None = None) -> HiddenGemScore: ...
```

`compute_final_score` metadata keys: `stars: int`, `created_at: datetime`,
optional `relevant_activity_age_days: int | None`, `relevance_evidence:
Sequence[str]`, `originality_evidence: Sequence[str]`.

Scoring is pure: no network, no SQLite, no implicit clock (explicit `as_of`).
Final relevance never exceeds the evidence cap derived from centrally verified
areas; originality is 0–10 from validated DeepAnalysis, or a conservative 0–4
in no-LLM mode from concrete differentiated-capability evidence.

## `hidden_gems.reporting`

```python
# fingerprints.py
def first_discovery_fingerprint(github_repo_id: int, score_version: str) -> str
def new_release_fingerprint(github_repo_id: int, release_id: int | str) -> str
def score_increase_fingerprint(github_repo_id: int, last_notification_id: int | str,
                               current_score: int) -> str
def major_change_fingerprint(github_repo_id: int, relevant_content_hash: str) -> str
def report_fingerprint(findings: Sequence[SelectedFinding], run_date: date,
                       score_version: str) -> str

# selector.py
@dataclass(frozen=True)
class RepoNotificationState:
    github_repo_id: int
    ever_seen: bool = False
    last_notified_score: int | None = None
    last_notification_id: int | None = None
    last_notified_at: datetime | None = None
    notified_fingerprints: frozenset[str] = frozenset()

def make_notification_decision(*, score: HiddenGemScore, stars: int,
                               state: RepoNotificationState, *,
                               release_fingerprint: str | None = None,
                               content_fingerprint: str | None = None,
                               config: AppConfig | None = None) -> NotificationDecision: ...

def select_report_candidates(findings: Sequence[SelectedFinding], *,
                             config: AppConfig | None = None) -> list[SelectedFinding]: ...

# markdown.py
def build_report(findings: Sequence[SelectedFinding], run_summary: RunSummary, *,
                 config: AppConfig | None = None) -> str: ...
def report_labels(findings: Sequence[SelectedFinding], *,
                  config: AppConfig | None = None) -> list[str]: ...
```

Selection: notification order is total score, then confidence rank
HIGH>MEDIUM>LOW, then novelty, visibility, activity points, then repo ID.
`normal_max` entries normally; positions 6–10 only when score >= 85; absolute
maximum 10; no padding; zero findings yields an empty string from
`build_report` (no report is published).

## `hidden_gems.security`

```python
# untrusted_content.py
def wrap_untrusted(text: str, *, max_chars: int | None = None) -> str: ...
def contains_prompt_injection(text: str) -> bool: ...

# sanitization.py
def sanitize_markdown_text(text: str, *, max_chars: int = 600) -> str: ...
def sanitize_inline(text: str, *, max_chars: int = 200) -> str: ...
```

## `hidden_gems.history`

```python
class HistoryStore:
    @classmethod
    def open(cls, path, *, migrations_dir: Path | None = None) -> "HistoryStore": ...
    def close(self) -> None: ...
    def migrate(self) -> None: ...
    def integrity_check(self) -> bool: ...
    @contextmanager
    def transaction(self): ...

    def get_repository(self, github_repo_id: int) -> dict[str, Any] | None: ...
    def upsert_repository(self, repo: RepositoryRef, *, stars: int = 0, created_at=None,
                          updated_at=None, primary_language=None, description=None,
                          seen_at: datetime | None = None, metadata: Mapping | None = None) -> None: ...
    def save_observation(self, github_repo_id: int, *, observed_at: datetime, run_id: str,
                         readme_hash: str | None = None, tree_hash: str | None = None,
                         dependency_hash: str | None = None,
                         relevant_content_hash: str | None = None,
                         activity_level: str | None = None,
                         detected_areas: Sequence[str] = (),
                         latest_release_tag: str | None = None,
                         latest_release_at: datetime | None = None,
                         latest_relevant_activity_at: datetime | None = None,
                         evidence: Mapping | None = None) -> None: ...
    def save_discovery_hit(self, github_repo_id: int, *, run_id: str, channel: str,
                           query_id: str, seen_at: datetime) -> None: ...
    def save_filter_decision(self, github_repo_id: int, *, run_id: str, decided_at: datetime,
                             passed: bool, reason_code: str | None,
                             evidence: Sequence[str] = ()) -> None: ...
    def save_score(self, github_repo_id: int, *, run_id: str, scored_at: datetime,
                   score: HiddenGemScore) -> None: ...
    def find_llm_analysis(self, *, github_repo_id: int, relevant_content_hash: str,
                          prompt_version: str, schema_version: str,
                          model: str) -> DeepAnalysis | None: ...
    def save_llm_analysis(self, github_repo_id: int, *, run_id: str, analyzed_at: datetime,
                          relevant_content_hash: str, prompt_version: str,
                          schema_version: str, model: str, analysis: DeepAnalysis,
                          input_tokens: int = 0, output_tokens: int = 0,
                          cost: float = 0.0) -> None: ...
    def save_notification(self, github_repo_id: int, *, fingerprint: str,
                          notification_type: str, score: int, notified_at: datetime,
                          run_id: str, issue_number: int | None = None,
                          previous_score: int | None = None) -> int: ...
    def latest_notification(self, github_repo_id: int) -> dict[str, Any] | None: ...
    def notification_exists(self, fingerprint: str) -> bool: ...
    def notification_state(self, github_repo_id: int) -> "RepoNotificationState": ...
    def save_pending_report(self, *, fingerprint: str, run_id: str, created_at: datetime,
                            payload: str) -> None: ...
    def find_pending_report(self, fingerprint: str | None = None) -> dict[str, Any] | None: ...
    def mark_report_published(self, fingerprint: str, *, issue_number: int, issue_url: str,
                              published_at: datetime, run_id: str) -> None: ...
    def start_run(self, *, run_id: str, started_at: datetime, dry_run: bool,
                  config_version: str, score_version: str, prompt_version: str,
                  budgets: Mapping[str, Any]) -> None: ...
    def finish_run(self, run_id: str, *, result: str, finished_at: datetime,
                   usage: Mapping[str, Any] | None = None,
                   report_fingerprint: str | None = None,
                   issue_number: int | None = None,
                   errors: Sequence[str] = ()) -> None: ...
```

Every connection enables `PRAGMA foreign_keys=ON`; `transaction()` commits on
success and rolls back on exception; `integrity_check()` returns True only when
SQLite reports exactly `ok`. `history` is the only module that writes SQLite.

## `hidden_gems.history.state_branch`

```python
@dataclass
class StateSnapshot:
    workdir: Path
    db_path: Path
    manifest: dict[str, Any]
    parent_sha: str | None
    last_run_id: str | None
    report_state: str

class StateConflict(Exception): ...

class StateBranchManager:
    def __init__(self, repo_root: Path, *, branch: str = "state",
                 db_filename: str = "history.sqlite3",
                 manifest_filename: str = "state_manifest.json",
                 max_backups: int = 3) -> None: ...
    def load(self, workdir: Path) -> StateSnapshot: ...
    def checkpoint_pending_report(self, snapshot: StateSnapshot,
                                  report_fingerprint: str) -> None: ...
    def persist(self, snapshot: StateSnapshot, expected_parent_sha: str | None) -> str: ...
    def rotate_backups(self, snapshot: StateSnapshot) -> None: ...
```

## `hidden_gems.orchestrator` / `cli`

```python
def run_pipeline(config: AppConfig, history: HistoryStore, github: GitHubClient,
                 llm: LLMProvider | None, context: RunContext, *,
                 publisher=None, as_of: datetime | None = None,
                 llm_enabled: bool | None = None) -> RunSummary: ...
```

CLI commands: `validate-config`, `migrate`, `db-check`, `run [--dry-run]`.
Every command prints one terminal `RESULT=<STATE>` line; configuration and
integrity failures exit non-zero.
