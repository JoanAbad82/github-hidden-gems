"""DeepAnalyzer: static, bounded, no-execution repository reading (SPEC_V1 §8)."""

from __future__ import annotations

import base64
from typing import Any, Mapping, Sequence

from ..config import AppConfig
from ..models import DeepAnalysis, LightAnalysis
from ..security.untrusted_content import contains_prompt_injection
from .evidence_builder import build_evidence
from .file_selector import SelectedFile, select_files

MAX_CONTEXT_CHARS = 2000


class DeepAnalyzer:
    """Reads a bounded set of files. Never executes, installs or builds."""

    def __init__(self, config: AppConfig, client: Any) -> None:
        self._config = config
        self._client = client

    # -- file access ------------------------------------------------------

    def _tree(self, light: LightAnalysis) -> list[Mapping[str, Any]]:
        ref = (light.evidence or {}).get("default_branch") or "HEAD"
        tree = self._client.get_tree(light.repo.full_name, ref)
        return [entry for entry in tree or () if isinstance(entry, Mapping)]

    def _read_file(self, light: LightAnalysis, path: str) -> str | None:
        ref = (light.evidence or {}).get("default_branch") or "HEAD"
        try:
            payload = self._client.get_json(
                f"/repos/{light.repo.full_name}/contents/{path}", {"ref": ref}
            )
        except Exception:
            return None
        if not isinstance(payload, Mapping):
            return None
        if payload.get("encoding") != "base64" or not payload.get("content"):
            return None
        try:
            raw = base64.b64decode(str(payload["content"]), validate=False)
        except Exception:
            return None
        limit = int(self._config.deep.max_file_bytes)
        return raw[:limit].decode("utf-8", errors="replace")

    def _collect(self, light: LightAnalysis) -> list[tuple[SelectedFile, str]]:
        selected = select_files(self._tree(light), config=self._config)
        collected: list[tuple[SelectedFile, str]] = []
        total = 0
        for item in selected:
            if total + item.size > int(self._config.deep.max_total_bytes):
                continue
            text = self._read_file(light, item.path)
            if text is None:
                continue
            total += item.size
            collected.append((item, text[:MAX_CONTEXT_CHARS]))
        return collected

    # -- analysis ---------------------------------------------------------

    def analyze(self, light: LightAnalysis) -> DeepAnalysis:
        files = self._collect(light)
        evidence = build_evidence(
            repo=light.repo, light=light, files=files, config=self._config
        )
        risks: list[str] = []
        for mismatch in evidence["claim_implementation_mismatch"]:
            risks.append(f"README claims '{mismatch}' but the tree shows a minimal implementation")
        if evidence["prompt_injection_signal"]:
            risks.append("repository text contains instruction-like content; it was fenced as data")
        if not evidence["observed"]["manifest_names"]:
            risks.append("no recognized dependency manifest")

        return DeepAnalysis(
            repo=light.repo,
            evidence=evidence,
            relevance_suggestion=None,
            originality_suggestion=None,
            why_interesting=None,
            summary=None,
            risks=tuple(risks),
            confidence=self._confidence(evidence),
            status="OK",
            source="PROVIDER",
        )

    @staticmethod
    def _confidence(evidence: Mapping[str, Any]) -> str:
        observed = evidence.get("observed", {})
        if observed.get("negative_signals") and not observed.get("source_file_count"):
            return "LOW"
        if observed.get("source_file_count") and observed.get("readme_present"):
            return "MEDIUM"
        return "LOW"
