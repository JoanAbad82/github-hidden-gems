"""Post-light semantic filtering must gate ranking/deep/LLM."""

from __future__ import annotations

import json

import pytest

from _pipeline_fakes import NOW, CountingLLM, FakeGitHub, payload, run_context

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="SQLite history not available"
).HistoryStore

from hidden_gems.orchestrator import run_pipeline  # noqa: E402


TUTORIAL_DESCRIPTION = (
    "Java + Spring Boot + LangChain4j 多 Agent 协同开发学习工程："
    "从最小对话到完整多 Agent 系统的渐进式教程"
)
TUTORIAL_README = """# Multi Agent Lab

这是一个循序渐进的教程，用于学习 multi-agent workflow automation。

包含多个模块、测试和完整实现，不是最小示例。
"""


class TutorialGitHub(FakeGitHub):
    def get_readme(self, full_name: str) -> str:
        return TUTORIAL_README

    def get_tree(self, full_name: str, ref: str) -> list[dict]:
        files = [
            {"path": "README.md", "type": "blob", "size": len(TUTORIAL_README)},
            {"path": "pom.xml", "type": "blob", "size": 200},
        ]
        files.extend(
            {"path": f"src/main/java/example/Module{index}.java", "type": "blob", "size": 120}
            for index in range(8)
        )
        files.extend(
            {"path": f"src/test/java/example/Module{index}Test.java", "type": "blob", "size": 90}
            for index in range(2)
        )
        return files


def test_post_light_tutorial_rejection_is_persisted_and_never_reaches_llm(
    app_config, tmp_path
):
    repo_id = 1379423359
    github = TutorialGitHub(
        [
            payload(
                repo_id,
                "AidenBJ",
                "java-multi-agent-lab",
                description=TUTORIAL_DESCRIPTION,
            )
        ]
    )
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        summary = run_pipeline(
            app_config,
            store,
            github,
            llm,
            run_context("RUN-POST-LIGHT-TUTORIAL"),
            as_of=NOW,
            llm_enabled=True,
        )

        assert llm.calls == 0
        assert summary.counts["rejected"] >= 1
        assert summary.counts["deep_analyzed"] == 0

        with store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT passed, reason_code, evidence
                FROM filter_decisions
                WHERE github_repo_id = ? AND run_id = ?
                ORDER BY rowid
                """,
                (repo_id, "RUN-POST-LIGHT-TUTORIAL"),
            ).fetchall()

        decoded = [
            (
                int(row["passed"]),
                row["reason_code"],
                json.loads(row["evidence"]),
            )
            for row in rows
        ]
        assert decoded[0][0] == 1, decoded
        assert any(
            passed == 0
            and reason == "REJECT_TUTORIAL"
            and "stage:post_light" in evidence
            and "description:tutorial_wording" in evidence
            and "readme:tutorial_wording" in evidence
            for passed, reason, evidence in decoded
        ), decoded
    finally:
        store.close()


def test_post_light_filter_keeps_normal_repository_eligible_for_llm(app_config, tmp_path):
    github = FakeGitHub([payload(9702, "acme-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        run_pipeline(
            app_config,
            store,
            github,
            llm,
            run_context("RUN-POST-LIGHT-CONTROL"),
            as_of=NOW,
            llm_enabled=True,
        )
        assert llm.calls >= 1
    finally:
        store.close()
