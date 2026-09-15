-- GitHub Hidden Gems V1 canonical SQLite schema (SPEC_V1 section 9).
-- Primary identity is the GitHub repository id; SQLite is the canonical history.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    github_repo_id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL UNIQUE,
    html_url TEXT NOT NULL,
    description TEXT,
    stars INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    pushed_at TEXT,
    primary_language TEXT,
    topics TEXT,
    metadata TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    current_score INTEGER,
    state TEXT NOT NULL DEFAULT 'NEW'
);

CREATE INDEX IF NOT EXISTS idx_repositories_last_seen_at ON repositories (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_repositories_current_score ON repositories (current_score);
CREATE INDEX IF NOT EXISTS idx_repositories_state ON repositories (state);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    readme_hash TEXT,
    tree_hash TEXT,
    dependency_hash TEXT,
    relevant_content_hash TEXT,
    activity_level TEXT,
    detected_areas TEXT,
    latest_release_tag TEXT,
    latest_release_at TEXT,
    latest_relevant_activity_at TEXT,
    evidence TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_repo ON observations (github_repo_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_run ON observations (run_id);

CREATE TABLE IF NOT EXISTS discovery_hits (
    hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    query_id TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    UNIQUE (github_repo_id, run_id, channel, query_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_hits_run ON discovery_hits (run_id);
CREATE INDEX IF NOT EXISTS idx_discovery_hits_repo ON discovery_hits (github_repo_id);

CREATE TABLE IF NOT EXISTS filter_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    passed INTEGER NOT NULL,
    reason_code TEXT,
    evidence TEXT
);

CREATE INDEX IF NOT EXISTS idx_filter_decisions_run ON filter_decisions (run_id);
CREATE INDEX IF NOT EXISTS idx_filter_decisions_repo ON filter_decisions (github_repo_id);

CREATE TABLE IF NOT EXISTS scores (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    relevance INTEGER NOT NULL,
    quality INTEGER NOT NULL,
    activity INTEGER NOT NULL,
    visibility INTEGER NOT NULL,
    novelty INTEGER NOT NULL,
    originality INTEGER NOT NULL,
    intersection INTEGER NOT NULL,
    total INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    score_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scores_repo ON scores (github_repo_id, scored_at);
CREATE INDEX IF NOT EXISTS idx_scores_run ON scores (run_id);
CREATE INDEX IF NOT EXISTS idx_scores_total ON scores (total);

CREATE TABLE IF NOT EXISTS llm_analyses (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    relevant_content_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    model TEXT NOT NULL,
    confidence TEXT,
    status TEXT,
    source TEXT,
    relevance_suggestion INTEGER,
    originality_suggestion INTEGER,
    why_interesting TEXT,
    summary TEXT,
    risks TEXT,
    evidence TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    UNIQUE (github_repo_id, relevant_content_hash, prompt_version, schema_version, model)
);

CREATE INDEX IF NOT EXISTS idx_llm_analyses_repo ON llm_analyses (github_repo_id);

CREATE TABLE IF NOT EXISTS releases (
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    release_id TEXT NOT NULL,
    tag_name TEXT,
    name TEXT,
    published_at TEXT,
    observed_at TEXT NOT NULL,
    prerelease INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (github_repo_id, release_id)
);

CREATE TABLE IF NOT EXISTS relationships (
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    related_repo_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    run_id TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    evidence TEXT,
    PRIMARY KEY (github_repo_id, related_repo_id, source_type)
);

CREATE INDEX IF NOT EXISTS idx_relationships_run ON relationships (run_id);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_repo_id INTEGER NOT NULL REFERENCES repositories (github_repo_id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    notification_type TEXT NOT NULL,
    score INTEGER NOT NULL,
    previous_score INTEGER,
    issue_number INTEGER,
    notified_at TEXT NOT NULL,
    run_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_repo ON notifications (github_repo_id, notified_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    dry_run INTEGER NOT NULL DEFAULT 1,
    config_version TEXT,
    score_version TEXT,
    prompt_version TEXT,
    budgets TEXT,
    usage TEXT,
    result TEXT,
    errors TEXT,
    report_fingerprint TEXT,
    report_payload TEXT,
    report_state TEXT NOT NULL DEFAULT 'NONE',
    issue_number INTEGER,
    issue_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at);
CREATE INDEX IF NOT EXISTS idx_runs_report_state ON runs (report_state);
