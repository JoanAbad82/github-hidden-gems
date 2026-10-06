"""Deterministic run artifacts for knowledge harvest."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

RUN_SCHEMA_VERSION = "KNOWLEDGE_HARVEST_RUN_V1"


def write_harvest_artifacts(
    output_dir: Path | str,
    *,
    run_id: str,
    repositories: Sequence[str],
    packets: Sequence[Mapping[str, Any]],
    errors: Sequence[str],
    usage: Mapping[str, Any],
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "knowledge_packets.json"
    csv_path = directory / "opportunities.csv"

    ordered_packets = sorted(
        (dict(packet) for packet in packets),
        key=lambda packet: str(packet["source"]["full_name"]).lower(),
    )
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": str(run_id),
        "repositories_requested": sorted(set(str(value) for value in repositories)),
        "packet_count": len(ordered_packets),
        "opportunity_count": sum(len(packet.get("opportunities", [])) for packet in ordered_packets),
        "errors": sorted(str(value) for value in errors),
        "usage": _json_safe(dict(usage)),
        "packets": ordered_packets,
    }
    _atomic_write(
        json_path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )

    fields = (
        "source_repo",
        "head_sha",
        "license_spdx_id",
        "target_project_id",
        "action",
        "title",
        "expected_benefit",
        "integration_cost",
        "risk",
        "evidence_refs",
        "rationale",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    rows: list[dict[str, Any]] = []
    for packet in ordered_packets:
        source = packet["source"]
        for opportunity in packet.get("opportunities", []):
            rows.append(
                {
                    "source_repo": source["full_name"],
                    "head_sha": source["head_sha"],
                    "license_spdx_id": source.get("license_spdx_id") or "",
                    "target_project_id": opportunity["target_project_id"],
                    "action": opportunity["action"],
                    "title": opportunity["title"],
                    "expected_benefit": opportunity["expected_benefit"],
                    "integration_cost": opportunity["integration_cost"],
                    "risk": opportunity["risk"],
                    "evidence_refs": ";".join(sorted(opportunity["evidence_refs"])),
                    "rationale": opportunity["rationale"],
                }
            )
    rows.sort(
        key=lambda row: (
            row["source_repo"].lower(),
            row["target_project_id"],
            _action_rank(row["action"]),
            row["title"].lower(),
        )
    )
    for row in rows:
        writer.writerow(row)
    _atomic_write(csv_path, buffer.getvalue())
    return json_path, csv_path


def _action_rank(value: str) -> int:
    return {"APPLY": 0, "EXPERIMENT": 1, "WATCH": 2, "DISCARD": 3}.get(str(value), 9)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
