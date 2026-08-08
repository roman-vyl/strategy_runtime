"""Final V1 dependency guardrails for Strategy Engine HTTP adapters."""

import ast
from pathlib import Path

STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE = Path("src/strategy_runtime/infrastructure/strategy_engine")


def _imported_modules(paths: tuple[Path, ...]) -> set[str]:
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def test_engine_adapter_package_has_no_outer_workflow_or_abi_dependency() -> None:
    assert tuple(STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE.glob("*.py"))
    imported = _imported_modules(tuple(STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE.glob("*.py")))

    forbidden_prefixes = (
        "strategy_runtime.bootstrap",
        "strategy_runtime.adapters",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.routing.router",
        "strategy_runtime.runtime.open_position.resolver",
        "strategy_runtime.runtime.entry_reconciliation_orchestrator",
        "strategy_runtime.runtime.state.repository",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.abi",
        "strategy_runtime.infrastructure.abi",
        "strategy_runtime.config",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
