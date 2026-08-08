"""Final V1 boundary guardrails for the entry-reconciliation execution bridge."""

import ast
from inspect import signature
from pathlib import Path
from typing import get_type_hints

from strategy_runtime.runtime.entry_reconciliation_bridge.bridge import (
    AbiEntryPackageExecutionBridge,
)

BRIDGE_PACKAGE = Path("src/strategy_runtime/runtime/entry_reconciliation_bridge")


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


def test_bridge_execute_signature_is_the_exact_transport_free_pair() -> None:
    parameters = signature(AbiEntryPackageExecutionBridge.execute).parameters
    assert tuple(parameters) == ("self", "command", "source_state")
    hints = get_type_hints(AbiEntryPackageExecutionBridge.execute)
    assert hints["command"].__name__ == "EntryReconciliationCommand"
    assert hints["source_state"].__name__ == "StrategyInstanceRuntimeState"


def test_bridge_package_owns_no_transport_coordination_or_persistence() -> None:
    assert tuple(BRIDGE_PACKAGE.glob("*.py"))
    imported = _imported_modules(tuple(BRIDGE_PACKAGE.glob("*.py")))

    forbidden_prefixes = (
        "fastapi",
        "httpx",
        "strategy_runtime.bootstrap",
        "strategy_runtime.adapters",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.routing",
        "strategy_runtime.runtime.open_position",
        "strategy_runtime.runtime.engine",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.state.repository",
        "strategy_runtime.config",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
