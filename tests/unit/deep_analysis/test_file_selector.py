"""Task 9: deep file selection priorities and budgets."""

from __future__ import annotations

from hidden_gems.deep_analysis.file_selector import select_files


def entry(path: str, size: int = 1000, kind: str = "blob") -> dict:
    return {"path": path, "type": kind, "size": size}


def test_selector_prioritizes_manifests_docs_tests_and_core_source(app_config):
    tree = [
        entry("src/app/main.py"),
        entry("tests/test_main.py"),
        entry("docs/usage.md"),
        entry("pyproject.toml"),
        entry("src/app/util.py"),
    ]

    selected = select_files(tree, config=app_config)

    assert [item.category for item in selected][:4] == ["manifest", "docs", "test", "source"]
    assert "pyproject.toml" in [item.path for item in selected]


def test_selector_excludes_binaries_datasets_and_lockfiles(app_config):
    tree = [
        entry("README.md"),
        entry("assets/logo.png"),
        entry("data/train.csv"),
        entry("model/weights.safetensors"),
        entry("poetry.lock"),
        entry("notebooks/analysis.ipynb"),
        entry("package-lock.json"),
    ]

    paths = [item.path for item in select_files(tree, config=app_config)]

    assert paths == ["README.md"]


def test_selector_excludes_vendored_and_generated_directories(app_config):
    tree = [
        entry("node_modules/pkg/index.js"),
        entry("dist/bundle.js"),
        entry("vendor/lib/lib.go"),
        entry("src/service.py"),
    ]

    paths = [item.path for item in select_files(tree, config=app_config)]

    assert paths == ["src/service.py"]


def test_selector_obeys_per_file_size_limit(app_config):
    tree = [entry("docs/huge.md", size=app_config.deep.max_file_bytes + 1), entry("docs/ok.md")]

    paths = [item.path for item in select_files(tree, config=app_config)]

    assert paths == ["docs/ok.md"]


def test_selector_obeys_total_content_budget(app_config):
    per_file = app_config.deep.max_file_bytes
    tree = [entry(f"docs/doc{index}.md", size=per_file) for index in range(20)]

    selected = select_files(tree, config=app_config)
    total = sum(item.size for item in selected)

    assert total <= app_config.deep.max_total_bytes
    assert len(selected) <= app_config.deep.max_files


def test_selector_obeys_per_category_limits(app_config):
    tree = [entry(f"tests/test_{index}.py") for index in range(10)]
    tree += [entry(f"docs/guide{index}.md") for index in range(10)]
    tree += [entry(f"src/module{index}.py") for index in range(10)]
    tree += [entry(f"pkg{index}/pyproject.toml") for index in range(5)]

    selected = select_files(tree, config=app_config)
    by_category: dict[str, int] = {}
    for item in selected:
        by_category[item.category] = by_category.get(item.category, 0) + 1

    assert by_category["test"] <= app_config.deep.max_test_files
    assert by_category["docs"] <= app_config.deep.max_docs_files
    assert by_category["source"] <= app_config.deep.max_source_files
    assert by_category["manifest"] <= app_config.deep.max_manifest_files
    assert len(selected) <= app_config.deep.max_files


def test_selection_is_deterministic_and_order_insensitive(app_config):
    tree = [entry("src/b.py"), entry("src/a.py"), entry("README.md"), entry("tests/test_a.py")]
    other = list(reversed(tree))

    assert select_files(tree, config=app_config) == select_files(other, config=app_config)


def test_directories_are_never_selected(app_config):
    tree = [entry("src", kind="tree"), entry("src/main.py")]

    assert [item.path for item in select_files(tree, config=app_config)] == ["src/main.py"]
