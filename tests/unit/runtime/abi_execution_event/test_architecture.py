"""Final V1 dependency guardrail for AbiExecutionEventOrchestrator."""

from __future__ import annotations

import ast
from pathlib import Path

ORCHESTRATOR = Path("src/strategy_runtime/runtime/abi_execution_event/orchestrator.py")


def _imported_modules() -> set[str]:
    tree = ast.parse(ORCHESTRATOR.read_text(encoding="utf-8"), filename=str(ORCHESTRATOR))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_orchestrator_depends_on_first_fill_transition_but_no_sibling_workflow() -> None:
    imported = _imported_modules()
    assert "strategy_runtime.runtime.first_fill.state_applier" in imported

    forbidden_prefixes = (
        "httpx",
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.config",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime.abi",
        "strategy_runtime.runtime.engine",
        "strategy_runtime.runtime.entry_reconciliation",
        "strategy_runtime.runtime.first_fill.alignment",
        "strategy_runtime.runtime.open_position",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.position_management",
        "strategy_runtime.runtime.routing",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
