import ast
from inspect import getsource, signature
from pathlib import Path
from typing import get_type_hints

from strategy_runtime.runtime.entry_reconciliation import (
    EntryReconciliationCommand,
    SuccessfulEntryConfirmation,
)
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationExecutionPort,
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.routing.models import LiveEntryProjectedStrategyInstance
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState

PACKAGE_ROOT = Path("src/strategy_runtime/runtime/entry_reconciliation_orchestrator")


def imported_modules() -> set[str]:
    imported: set[str] = set()
    for path in PACKAGE_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def test_application_package_has_only_approved_direct_dependencies() -> None:
    assert tuple(PACKAGE_ROOT.glob("*.py"))
    allowed_prefixes = (
        "typing",
        "strategy_runtime.runtime.entry_reconciliation",
        "strategy_runtime.runtime.entry_reconciliation_orchestrator",
        "strategy_runtime.runtime.routing.models",
        "strategy_runtime.runtime.state.identity",
        "strategy_runtime.runtime.state.models",
    )

    assert all(
        any(name == prefix or name.startswith(f"{prefix}.") for prefix in allowed_prefixes)
        for name in imported_modules()
    )


def test_application_package_has_no_outer_workflow_or_adapter_dependency() -> None:
    forbidden_prefixes = (
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime.abi",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.engine",
        "strategy_runtime.runtime.open_position",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.state.repository",
    )
    imported = imported_modules()

    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )

    source = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE_ROOT.glob("*.py"))
    forbidden_behavior = (
        "EntryPackageRequest",
        "EntryPackageResult",
        "AbiEntryPackagePort",
        "repository",
        "keyed_mutex",
        "httpx",
        "fastapi",
        "retry",
        "bootstrap",
        "infrastructure",
    )
    for token in forbidden_behavior:
        assert token not in source


def test_operation_acquires_its_only_state_from_the_projection() -> None:
    parameters = signature(EntryReconciliationOrchestrator.execute).parameters
    assert tuple(parameters) == ("self", "projection")
    hints = get_type_hints(EntryReconciliationOrchestrator.execute)
    assert hints["projection"] is LiveEntryProjectedStrategyInstance
    assert hints["return"] is StrategyInstanceRuntimeState

    source = getsource(EntryReconciliationOrchestrator.execute)
    assert source.count("projection.source.resolved_state.runtime_state") == 1
    assert "repository" not in source
    assert ".save(" not in source
    assert ".get(" not in source


def test_execution_port_is_the_exact_transport_free_pair() -> None:
    parameters = signature(EntryReconciliationExecutionPort.execute).parameters
    assert tuple(parameters) == ("self", "command", "source_state")
    hints = get_type_hints(EntryReconciliationExecutionPort.execute)
    assert hints["command"] is EntryReconciliationCommand
    assert hints["source_state"] is StrategyInstanceRuntimeState
    assert hints["return"] == SuccessfulEntryConfirmation

    port_source = getsource(EntryReconciliationExecutionPort)
    assert "runtime.abi" not in port_source
    assert "Request" not in port_source
    assert "Result" not in port_source
    assert "http" not in port_source.lower()
    assert "codec" not in port_source.lower()


def test_public_package_boundary_exports_only_operation_and_port() -> None:
    import strategy_runtime.runtime.entry_reconciliation_orchestrator as boundary

    assert boundary.__all__ == (
        "EntryReconciliationExecutionPort",
        "EntryReconciliationOrchestrator",
    )
