"""Read-only targeted DeepSeek probe for one GitHub repository.

This diagnostic bypasses discovery ranking only. It reuses the production
LightAnalyzer -> DeepAnalyzer -> DeepSeekProvider path and never publishes,
scores, or persists repository state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from hidden_gems.common.time import utcnow
from hidden_gems.config import load_config
from hidden_gems.deep_analysis.analyzer import DeepAnalyzer
from hidden_gems.github.client import GitHubClient
from hidden_gems.github.repositories import payload_to_candidate
from hidden_gems.light_analysis.analyzer import LightAnalyzer
from hidden_gems.llm.deepseek import DeepSeekProvider


def _safe_attempts(snapshot: dict) -> list[dict]:
    allowed = {
        "repo_id",
        "attempt",
        "http_status",
        "finish_reason",
        "prompt_tokens",
        "completion_tokens",
        "content_length",
        "validation_result",
    }
    return [
        {key: item.get(key) for key in sorted(allowed) if key in item}
        for item in snapshot.get("attempts", [])
        if isinstance(item, dict)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config = load_config(root)

    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise SystemExit("GITHUB_TOKEN is required")
    if not os.environ.get(config.llm.api_key_env_var):
        raise SystemExit(f"{config.llm.api_key_env_var} is required")

    client = GitHubClient(config, github_token)
    try:
        payload = client.get_repo_metadata(args.repo)
        candidate = payload_to_candidate(payload, channels=("TARGETED_DIAGNOSTIC",))
        if candidate is None:
            raise SystemExit("repository metadata could not form a canonical candidate")

        light = LightAnalyzer(config, client).analyze(candidate, as_of=utcnow())
        deep = DeepAnalyzer(config, client).analyze(light)

        provider = DeepSeekProvider(config)
        result = provider.analyze_repository(deep.evidence)
        snapshot = provider.budget.snapshot()

        print(f"TARGET_REPO={candidate.repo.full_name}")
        print(f"TARGET_REPO_ID={candidate.repo.github_repo_id}")
        print(f"LIGHT_SOURCE_FILES={int((light.evidence or {}).get('source_file_count', 0) or 0)}")
        print(f"DEEP_STATUS={deep.status}")
        print(f"LLM_STATUS={result.status}")
        print(f"LLM_FAILURES={int(snapshot.get('failures', 0) or 0)}")
        print("LLM_REASONS=" + json.dumps(snapshot.get("reasons", {}), sort_keys=True))
        print("LLM_ATTEMPTS=" + json.dumps(_safe_attempts(snapshot), sort_keys=True))
        if result.status != "OK":
            evidence = result.evidence if isinstance(result.evidence, dict) else {}
            print("FAILURE=" + str(evidence.get("failure", "unknown")))
            print("FAILURE_REASON=" + " ".join(str(evidence.get("failure_reason", "")).split())[:400])
            return 2
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
