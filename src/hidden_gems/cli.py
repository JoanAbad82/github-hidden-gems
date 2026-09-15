"""Command line entry point.

Every command prints exactly one terminal `RESULT=<STATE>` line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hidden-gems", description="GitHub Hidden Gems V1")
    parser.add_argument("--root", default=".", help="project root containing config/ (default: .)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate configuration and exit")
    validate.add_argument("--root", dest="sub_root", default=None, help="project root (overrides global --root)")

    return parser


def resolve_root(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "sub_root", None) or args.root).resolve()


def cmd_validate_config(args: argparse.Namespace) -> int:
    root = resolve_root(args)
    try:
        load_config(root)
    except ConfigError as exc:
        print(f"RESULT=FAILED_CONFIGURATION")
        print(f"ERROR={exc}")
        return 2
    print("RESULT=CONFIG_VALID")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "validate-config": cmd_validate_config,
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover - argparse restricts commands
        parser.error(f"unknown command {args.command!r}")
        return 2
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
