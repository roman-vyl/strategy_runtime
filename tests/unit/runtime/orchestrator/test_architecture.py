"""Architecture and scope guardrail tests for Runtime orchestrator change."""

from __future__ import annotations

import ast
from pathlib import Path

ORCHESTRATOR_PACKAGE = Path("src/strategy_runtime/runtime/orchestrator")
RECONCILIATION_PACKAGE = Path("src/strategy_runtime/runtime/entry_reconciliation_orchestrator")


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


def test_orchestrator_composes_existing_components() -> None:
    """7.1: This change modifies the existing Runtime orchestrator and composes
    existing repository, mutex, resolver, router/projection, state, and
    nested reconciliation boundaries."""
    source_path = ORCHESTRATOR_PACKAGE / "orchestrator.py"
    source = source_path.read_text(encoding="utf-8")

    assert "StrategyInstanceRuntimeStateRepository" in source
    assert "StrategyInstanceKeyedMutexRegistry" in source
    assert "OpenPositionResolverPort" in source
    assert "StrategyUseCaseRouterPort" in source
    assert "EntryReconciliationOrchestrator" in source
    assert "StrategyInstanceRuntimeState" in source
    assert "LiveEntryProjectedStrategyInstance" in source
    assert "OpenTradeProjectedStrategyInstance" in source


def test_entry_reconciliation_orchestrator_free_of_mutex_repository_workflow() -> None:
    """7.2: EntryReconciliationOrchestrator has no keyed-mutex, repository
    get/load/save, top-level workflow, or production adapter ownership."""
    imported = _imported_modules(RECONCILIATION_PACKAGE)

    forbidden_prefixes = (
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.state.repository",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.infrastructure",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )

    source = "\n".join(
        path.read_text(encoding="utf-8") for path in RECONCILIATION_PACKAGE.glob("*.py")
    )
    forbidden_tokens = (
        "keyed_mutex",
        "repository",
        ".save(",
        ".get_or_create(",
        "CommittedBarOrchestrator",
        "StrategyCycleDispatchOutcome",
        "StrategyCycleHandoffBoundary",
        "handoff",
    )
    for token in forbidden_tokens:
        assert token not in source, (
            f"forbidden token '{token}' in entry_reconciliation_orchestrator"
        )


def test_no_production_wiring_or_adapter_changes() -> None:
    """7.3: No production handoff wiring, bootstrap, engine HTTP adapter,
    ABI HTTP adapter, entry-reconciliation execution adapter, Runtime URL
    config, Docker, or cross-service integration test is changed."""
    source_path = ORCHESTRATOR_PACKAGE / "orchestrator.py"
    source = source_path.read_text(encoding="utf-8")

    forbidden_tokens = (
        "StrategyCycleHandoffBoundary",
        "bootstrap",
        "httpx",
        "fastapi",
        "uvicorn",
        "docker",
        "Docker",
        "retry",
        "fallback",
    )
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in orchestrator"


def test_utility_committed_bar_layer_unchanged() -> None:
    """7.4: Utility committed-bar layer does not contain semantic reconciliation logic."""
    source_path = Path("src/strategy_runtime/utility/committed_bar/orchestrator.py")
    source = source_path.read_text(encoding="utf-8")

    forbidden_tokens = (
        "decide_entry_reconciliation",
        "build_entry_reconciliation_command",
        "apply_success_confirmation",
        "EntryReconciliationOrchestrator",
        "LiveEntryProjectedStrategyInstance",
        "OpenTradeProjectedStrategyInstance",
        "StrategyInstanceRuntimeState",
        "keyed_mutex",
    )
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in utility committed_bar"


def test_canonical_openspec_unchanged() -> None:
    """7.4: Canonical OpenSpec files are not modified during implementation."""
    spec_path = Path("openspec/specs/strategy-runtime-orchestrator/spec.md")
    if spec_path.exists():
        source = spec_path.read_text(encoding="utf-8")
        assert "typed post-projection" not in source.lower()
