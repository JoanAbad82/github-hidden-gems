"""Command line entry point.

Every command prints exactly one terminal `RESULT=<STATE>` line. Configuration
and integrity failures exit non-zero.
"""

from __future__ import annotations

import argparse
import os
import sys
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
    if env_flag or args.dry_run:
        return True
    return not args.live


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
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse restricts commands
        parser.error(f"unknown command {args.command!r}")
        return 2
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
