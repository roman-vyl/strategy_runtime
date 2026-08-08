"""Final V1 dependency-direction guardrails for Runtime orchestration."""

from __future__ import annotations

import ast
from pathlib import Path

ORCHESTRATOR_PACKAGE = Path("src/strategy_runtime/runtime/orchestrator")
UTILITY_COMMITTED_BAR_PACKAGE = Path("src/strategy_runtime/utility/committed_bar")


def _imported_modules(package_root: Path) -> set[str]:
    imported: set[str] = set()
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def test_runtime_orchestrator_has_no_adapter_or_infrastructure_dependency() -> None:
    imported = _imported_modules(ORCHESTRATOR_PACKAGE)

    forbidden_prefixes = (
        "httpx",
        "fastapi",
        "uvicorn",
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.config",
        "strategy_runtime.infrastructure",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )


def test_utility_committed_bar_has_no_runtime_or_infrastructure_dependency() -> None:
    imported = _imported_modules(UTILITY_COMMITTED_BAR_PACKAGE)

    forbidden_prefixes = (
        "httpx",
        "fastapi",
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.config",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
