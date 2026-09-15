"""Command line entry point.

Every command prints exactly one terminal `RESULT=<STATE>` line. Configuration
and integrity failures exit non-zero.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from .common.logging import configure_logging
from .common.time import utcnow
from .config import ConfigError, load_config, resolve_llm_enabled
from .models import RunContext
from .orchestrator import run_pipeline
from .llm.base import DisabledLLMProvider
from .llm.cache import CachedLLMProvider
from .llm.deepseek import DeepSeekProvider
from .llm.validator import PROMPT_VERSION

NON_RETRYABLE_RESULTS = ("FAILED_INTEGRITY", "FAILED_CONFIGURATION")

#: Task 17 controlled-live gate: strictly lower limits than production
#: (SPEC_V1 section 3 budgets are the production maxima).
CONTROLLED_LIVE_LIMITS: dict[str, int] = {
    "max_raw_candidates": 30,
    "max_light_analysis": 10,
    "max_deep_analysis": 3,
    "max_llm_calls_per_run": 2,
}

#: Acceptance-gate exit codes (`hidden-gems validation-status`).
EXIT_BY_VALIDATION_STATUS = {
    "V1_ACCEPTED": 0,
    "V1_NOT_ACCEPTED": 1,
    "PENDING_MULTI_DAY_VALIDATION": 2,
}

RESULT_BY_VALIDATION_STATUS = {
    "V1_ACCEPTED": "VALIDATION_ACCEPTED",
    "V1_NOT_ACCEPTED": "VALIDATION_NOT_ACCEPTED",
    "PENDING_MULTI_DAY_VALIDATION": "VALIDATION_PENDING",
}


def _history_store():
    """Import the canonical SQLite store lazily (history owns that module)."""

    from .history.database import HistoryStore

    return HistoryStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hidden-gems", description="GitHub Hidden Gems V1")
    parser.add_argument("--root", default=".", help="project root containing config/ (default: .)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate configuration and exit")
    _add_root(validate)

    migrate = subparsers.add_parser("migrate", help="create or migrate the SQLite history database")
    _add_root(migrate)
    migrate.add_argument("--db", dest="db_path", default=None, help="database path override")

    db_check = subparsers.add_parser("db-check", help="verify SQLite integrity")
    _add_root(db_check)
    db_check.add_argument("--db", dest="db_path", default=None, help="database path override")

    run = subparsers.add_parser("run", help="run one discovery cycle")
    _add_root(run)
    run.add_argument("--dry-run", action="store_true", help="never publish an Issue")
    run.add_argument(
        "--live",
        action="store_true",
        help="allow publication (requires GITHUB_REPOSITORY and a non-dry-run environment)",
    )
    run.add_argument("--db", dest="db_path", default=None, help="database path override")
    run.add_argument(
        "--llm",
        dest="llm",
        action="store_true",
        default=None,
        help="force semantic enrichment on (default: configuration)",
    )
    run.add_argument("--no-llm", dest="llm", action="store_false", help="disable semantic enrichment")
    run.add_argument(
        "--controlled-live",
        action="store_true",
        help=(
            "controlled-live gate: forced dry-run with reduced limits "
            f"({CONTROLLED_LIVE_LIMITS['max_raw_candidates']} seen / "
            f"{CONTROLLED_LIVE_LIMITS['max_light_analysis']} light / "
            f"{CONTROLLED_LIVE_LIMITS['max_deep_analysis']} deep / "
            f"{CONTROLLED_LIVE_LIMITS['max_llm_calls_per_run']} LLM calls)"
        ),
    )
    run.add_argument("--max-raw-candidates", type=int, default=None, help="lower the seen-repository budget")
    run.add_argument("--max-light", type=int, default=None, help="lower the light-analysis budget")
    run.add_argument("--max-deep", type=int, default=None, help="lower the deep-analysis budget")
    run.add_argument("--max-llm-calls", type=int, default=None, help="lower the LLM call budget")

    validation = subparsers.add_parser(
        "validation-status", help="evaluate the seven-cycle V1 acceptance gate (read-only)"
    )
    _add_root(validation)
    validation.add_argument("--db", dest="db_path", default=None, help="database path override")
    validation.add_argument(
        "--gradings",
        dest="gradings_path",
        default=None,
        help="YAML/JSON file with human GOOD/MAYBE/BAD gradings per notified repository",
    )
    validation.add_argument("--cycles", dest="cycles", type=int, default=7, help="required consecutive cycles")
    validation.add_argument(
        "--markdown",
        dest="markdown_path",
        default=None,
        help="write the rendered acceptance report to this path",
    )
    return parser


def _add_root(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--root",
        dest="sub_root",
        default=None,
        help="project root containing config/ (overrides the global --root)",
    )


def _want_dry_run(args: argparse.Namespace) -> bool:
    """Dry-run is the default. Publication needs an explicit --live and no DRY_RUN=true."""

    env_flag = os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
    if env_flag or args.dry_run or getattr(args, "controlled_live", False):
        return True
    return not args.live


def apply_run_overrides(config, args: argparse.Namespace):
    """Apply reduced run budgets. An override may only lower a configured limit."""

    requested: dict[str, int] = {}
    if getattr(args, "controlled_live", False):
        requested.update(CONTROLLED_LIVE_LIMITS)
    for attribute, key in (
        ("max_raw_candidates", "max_raw_candidates"),
        ("max_light", "max_light_analysis"),
        ("max_deep", "max_deep_analysis"),
        ("max_llm_calls", "max_llm_calls_per_run"),
    ):
        value = getattr(args, attribute, None)
        if value is None:
            continue
        if int(value) < 0:
            raise ConfigError(f"--{attribute.replace('_', '-')} must not be negative")
        requested[key] = int(value)
    if not requested:
        return config

    budgets = dict(config.limits.run_budgets)
    llm = config.llm
    for key, value in requested.items():
        if key == "max_llm_calls_per_run":
            current = int(config.llm.max_llm_calls_per_run)
            if value > current:
                raise ConfigError(
                    f"max_llm_calls_per_run={value} may only lower the configured limit {current}"
                )
            llm = replace(llm, max_llm_calls_per_run=value)
            continue
        current = int(budgets.get(key, 0))
        if value > current:
            raise ConfigError(f"{key}={value} may only lower the configured limit {current}")
        budgets[key] = value

    if "max_deep_analysis" in budgets and "max_light_analysis" in budgets:
        if budgets["max_deep_analysis"] > budgets["max_light_analysis"]:
            raise ConfigError("max_deep_analysis must not exceed max_light_analysis")
    limits = replace(config.limits, run_budgets=budgets, llm=llm)
    return replace(config, limits=limits, llm=llm)


def resolve_root(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "sub_root", None) or args.root).resolve()


def resolve_db_path(config, args: argparse.Namespace) -> Path:
    override = getattr(args, "db_path", None) or os.environ.get("HIDDEN_GEMS_DB")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(config.root) / "state" / config.state.database_filename).resolve()


def cmd_validate_config(args: argparse.Namespace) -> int:
    root = resolve_root(args)
    try:
        load_config(root)
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2
    print("RESULT=CONFIG_VALID")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    try:
        config = load_config(resolve_root(args))
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2
    store = _history_store().open(resolve_db_path(config, args))
    try:
        store.migrate()
        if not store.integrity_check():
            print("RESULT=FAILED_INTEGRITY")
            return 3
    finally:
        store.close()
    print("RESULT=DB_MIGRATED")
    return 0


def cmd_db_check(args: argparse.Namespace) -> int:
    try:
        config = load_config(resolve_root(args))
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2
    path = resolve_db_path(config, args)
    if not path.exists():
        print("RESULT=FAILED_INTEGRITY")
        print(f"ERROR=database not found: {path}")
        return 3
    store = _history_store().open(path)
    try:
        healthy = store.integrity_check()
    finally:
        store.close()
    if not healthy:
        print("RESULT=FAILED_INTEGRITY")
        return 3
    print("RESULT=DB_VALID")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        config = load_config(resolve_root(args))
        config = apply_run_overrides(config, args)
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2

    store = _history_store().open(resolve_db_path(config, args))
    github = None
    try:
        store.migrate()
        if not store.integrity_check():
            print("RESULT=FAILED_INTEGRITY")
            return 3

        from .github.client import GitHubClient

        github = GitHubClient(config, os.environ.get("GITHUB_TOKEN"))
        dry_run = _want_dry_run(args)
        context = RunContext(
            run_id=f"RUN-{utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            started_at=utcnow(),
            dry_run=dry_run,
            config_version=config.config_version,
            score_version=config.scoring.score_version,
            prompt_version=PROMPT_VERSION,
        )
        if args.llm is None:
            # `LLM_ENABLED` is the documented/workflow variable; `--llm`/`--no-llm` win.
            enabled = resolve_llm_enabled(config, os.environ)
        else:
            enabled = bool(args.llm)
        llm = _build_llm(config, store, context, enabled)
        publisher = None
        if not dry_run:
            from .github.issues import GitHubIssuePublisher

            repository = os.environ.get("GITHUB_REPOSITORY")
            if not repository:
                print("RESULT=FAILED_CONFIGURATION")
                print("ERROR=GITHUB_REPOSITORY is required for a live run")
                return 2
            publisher = GitHubIssuePublisher(config, github, repository=repository)
        summary = run_pipeline(
            config, store, github, llm, context, publisher=publisher, llm_enabled=enabled
        )
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2
    finally:
        if github is not None:
            github.close()
        store.close()

    print(f"RESULT={summary.result}")
    if summary.result in NON_RETRYABLE_RESULTS:
        return 2
    return 0


def cmd_validation_status(args: argparse.Namespace) -> int:
    """Evaluate the seven-cycle acceptance gate from persisted evidence only."""

    from .validation.acceptance import (
        AcceptanceCriteria,
        cycles_from_history,
        evaluate_acceptance,
        load_gradings,
        render_acceptance_markdown,
    )

    try:
        config = load_config(resolve_root(args))
    except ConfigError as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2

    path = resolve_db_path(config, args)
    if not path.exists():
        print("RESULT=FAILED_INTEGRITY")
        print(f"ERROR=database not found: {path}")
        return 3

    gradings_path = getattr(args, "gradings_path", None)
    try:
        gradings = load_gradings(gradings_path) if gradings_path else {}
    except Exception as exc:
        print("RESULT=FAILED_CONFIGURATION")
        print(f"ERROR=invalid gradings file: {type(exc).__name__}")
        return 2

    store = _history_store().open(path)
    try:
        if not store.integrity_check():
            print("RESULT=FAILED_INTEGRITY")
            return 3
        cycles = cycles_from_history(store, gradings=gradings)
    finally:
        store.close()

    report = evaluate_acceptance(
        cycles,
        criteria=AcceptanceCriteria(required_cycles=max(1, int(getattr(args, "cycles", 7) or 7))),
    )
    markdown = render_acceptance_markdown(report)
    markdown_path = getattr(args, "markdown_path", None)
    if markdown_path:
        Path(markdown_path).expanduser().write_text(markdown, encoding="utf-8")

    metrics = report.metrics
    print(f"CYCLES_OBSERVED={metrics.get('cycles_observed', 0)}")
    print(f"CONSECUTIVE_CYCLES={metrics.get('consecutive_cycles', 0)}")
    rate = metrics.get("useful_discovery_rate")
    print(f"USEFUL_DISCOVERY_RATE={'n/a' if rate is None else f'{rate:.2%}'}")
    print(f"ISSUES_CREATED={metrics.get('issues_created', 0)}")
    for reason in report.blocking:
        print(f"REASON={reason}")
    print(f"STATUS={report.status}")
    print(f"RESULT={RESULT_BY_VALIDATION_STATUS.get(report.status, 'VALIDATION_PENDING')}")
    return EXIT_BY_VALIDATION_STATUS.get(report.status, 2)


def _build_llm(config, store, context: RunContext, enabled: bool):
    if not enabled:
        return DisabledLLMProvider()
    provider = DeepSeekProvider(config)
    return CachedLLMProvider(
        provider,
        store,
        run_id=context.run_id,
        model=config.llm.model,
        budget=provider.budget,
    )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "validate-config": cmd_validate_config,
        "migrate": cmd_migrate,
        "db-check": cmd_db_check,
        "run": cmd_run,
        "validation-status": cmd_validation_status,
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse restricts commands
        parser.error(f"unknown command {args.command!r}")
        return 2
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
