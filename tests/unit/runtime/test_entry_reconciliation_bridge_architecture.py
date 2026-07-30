"""Architecture and scope guardrails for the entry-reconciliation execution bridge (I4c)."""

import ast
from inspect import signature
from pathlib import Path
from typing import get_type_hints

from strategy_runtime.runtime.entry_reconciliation_bridge.bridge import (
    AbiEntryPackageExecutionBridge,
)

BRIDGE_PACKAGE = Path("src/strategy_runtime/runtime/entry_reconciliation_bridge")
WIRED_COMPONENT_PATHS = (
    Path("src/strategy_runtime/bootstrap/application.py"),
    Path("src/strategy_runtime/bootstrap/main.py"),
    Path("src/strategy_runtime/runtime/orchestrator/orchestrator.py"),
    Path("src/strategy_runtime/runtime/routing/router.py"),
    Path("src/strategy_runtime/runtime/open_position/resolver.py"),
    Path("src/strategy_runtime/runtime/entry_reconciliation_orchestrator/orchestrator.py"),
    Path("src/strategy_runtime/config/loader.py"),
)


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


def test_bridge_owns_no_http_transport() -> None:
    """9.2: no httpx import, no URL/timeout configuration in the bridge package."""
    assert tuple(BRIDGE_PACKAGE.glob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in BRIDGE_PACKAGE.glob("*.py"))

    forbidden_tokens = (
        "httpx",
        "base_url",
        "timeout_seconds",
        "follow_redirects",
        "keyed_mutex",
        "repository",
        ".save(",
        ".get_or_create(",
    )
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in bridge package"


def test_bridge_execute_signature_is_the_exact_transport_free_pair() -> None:
    parameters = signature(AbiEntryPackageExecutionBridge.execute).parameters
    assert tuple(parameters) == ("self", "command", "source_state")
    hints = get_type_hints(AbiEntryPackageExecutionBridge.execute)
    assert hints["command"].__name__ == "EntryReconciliationCommand"
    assert hints["source_state"].__name__ == "StrategyInstanceRuntimeState"


def test_bridge_is_wired_into_production_composition_by_i4d() -> None:
    """I4d composes the bridge into `build_application`, inverting the I4c
    -era guardrail that proved it was implemented in isolation with zero
    production wiring. The bridge's own internal purity (no HTTP/mutex/
    repository ownership, tested above) is unaffected by this wiring."""
    imported = _imported_modules(WIRED_COMPONENT_PATHS)

    assert any(
        name == "strategy_runtime.runtime.entry_reconciliation_bridge"
        or name.startswith("strategy_runtime.runtime.entry_reconciliation_bridge.")
        for name in imported
    )

    application_source = Path("src/strategy_runtime/bootstrap/application.py").read_text(
        encoding="utf-8"
    )
    assert "AbiEntryPackageExecutionBridge" in application_source


def test_bridge_package_has_no_forbidden_dependencies() -> None:
    imported = _imported_modules(tuple(BRIDGE_PACKAGE.glob("*.py")))

    forbidden_prefixes = (
        "strategy_runtime.bootstrap",
        "strategy_runtime.adapters",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.routing",
        "strategy_runtime.runtime.open_position",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.state.repository",
        "strategy_runtime.config",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )


def test_entry_reconciliation_orchestrator_package_still_forbids_abi_import() -> None:
    """Guard that the bridge was not placed inside entry_reconciliation_orchestrator,
    which the existing architecture test already forbids from importing runtime.abi."""
    package_root = Path("src/strategy_runtime/runtime/entry_reconciliation_orchestrator")
    imported = _imported_modules(tuple(package_root.glob("*.py")))
    assert not any(
        name == "strategy_runtime.runtime.abi" or name.startswith("strategy_runtime.runtime.abi.")
        for name in imported
    )
