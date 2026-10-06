"""Run KNOWLEDGE_HARVEST_V1 across explicitly selected repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifacts import write_harvest_artifacts
from .collector import collect_repository_evidence
from .validator import PACKET_SCHEMA_VERSION


def repositories_from_candidates(path: Path | str, *, top: int = 3) -> list[str]:
    """Read selected report repositories from RUN_CANDIDATES_V1 output."""

    candidate_path = Path(path)
    if candidate_path.is_dir():
        matches = sorted(candidate_path.rglob("candidates.json"))
        if not matches:
            return []
        candidate_path = matches[-1]
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") or []
    selected: list[tuple[int, str]] = []
    for item in candidates:
        if not isinstance(item, Mapping) or not item.get("selected_for_report"):
            continue
        repo = item.get("repository") or {}
        full_name = str(repo.get("full_name") or "")
        rank = item.get("report_rank")
        if full_name and isinstance(rank, int):
            selected.append((rank, full_name))
    selected.sort(key=lambda pair: (pair[0], pair[1].lower()))
    return [full_name for _, full_name in selected[: max(1, int(top))]]


def harvest_repositories(
    *,
    github: Any,
    provider: Any,
    repositories: Sequence[str],
    output_dir: Path | str,
    run_id: str,
) -> dict[str, Any]:
    packets: list[dict[str, Any]] = []
    errors: list[str] = []

    unique_repositories = sorted(
        {str(value).strip() for value in repositories if str(value).strip()},
        key=str.lower,
    )
    for full_name in unique_repositories:
        try:
            evidence = collect_repository_evidence(github, full_name)
            analysis = provider.analyze(evidence)
            packets.append(
                {
                    "schema_version": PACKET_SCHEMA_VERSION,
                    "prompt_version": provider.prompt_version,
                    "model": provider.model,
                    "source": evidence["source"],
                    "reuse_policy": "ADAPT_CONCEPT",
                    **analysis,
                }
            )
        except Exception as exc:
            errors.append(f"{full_name}:{type(exc).__name__}:{' '.join(str(exc).split())[:220]}")

    usage = (
        dict(provider.budget.snapshot())
        if getattr(provider, "budget", None) is not None
        else {}
    )
    json_path, csv_path = write_harvest_artifacts(
        output_dir,
        run_id=run_id,
        repositories=unique_repositories,
        packets=packets,
        errors=errors,
        usage=usage,
    )
    return {
        "run_id": run_id,
        "requested": len(unique_repositories),
        "packets": packets,
        "errors": errors,
        "json_path": json_path,
        "csv_path": csv_path,
        "usage": usage,
    }
