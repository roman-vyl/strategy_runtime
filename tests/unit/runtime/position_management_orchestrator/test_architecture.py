"""Guardrail: the position-management orchestrator owns no mutex or repository."""

import ast
from pathlib import Path

PACKAGE = Path("src/strategy_runtime/runtime/position_management_orchestrator")

FORBIDDEN_IMPORT_PREFIXES = (
    "strategy_runtime.runtime.coordination",
    "strategy_runtime.runtime.state.repository",
    "strategy_runtime.runtime.orchestrator",
    "strategy_runtime.adapters",
    "strategy_runtime.bootstrap",
    "strategy_runtime.config",
    "strategy_runtime.infrastructure",
)


def _imported_modules() -> set[str]:
    imported: set[str] = set()
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def test_orchestrator_package_imports_no_coordination_or_persistence_module() -> None:
    imported = _imported_modules()

    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )
