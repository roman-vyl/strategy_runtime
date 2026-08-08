"""Final V1 dependency guardrails for ABI lookup and entry-package adapters."""

import ast
from pathlib import Path

import strategy_runtime.runtime.abi as runtime_abi
from strategy_runtime.infrastructure.abi.http_entry_package import (
    HttpxAbiEntryPackageAdapter,
)

OPEN_POSITION_ADAPTER = Path("src/strategy_runtime/infrastructure/abi/http_open_position.py")
OPEN_POSITION_RESOLVER = Path("src/strategy_runtime/runtime/open_position/resolver.py")


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


def test_open_position_adapter_has_no_outer_workflow_or_entry_package_dependency() -> None:
    imported = _imported_modules((OPEN_POSITION_ADAPTER,))

    forbidden_prefixes = (
        "strategy_runtime.bootstrap",
        "strategy_runtime.adapters",
        "strategy_runtime.runtime.orchestrator",
        "strategy_runtime.runtime.routing",
        "strategy_runtime.runtime.open_position.resolver",
        "strategy_runtime.runtime.entry_reconciliation_orchestrator",
        "strategy_runtime.runtime.state.repository",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.abi",
        "strategy_runtime.config",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )


def test_entry_package_http_adapter_is_infrastructure_owned() -> None:
    assert (
        HttpxAbiEntryPackageAdapter.__module__
        == "strategy_runtime.infrastructure.abi.http_entry_package"
    )
    assert not hasattr(runtime_abi, "HttpxAbiEntryPackageAdapter")


def test_open_position_resolver_is_transport_free() -> None:
    imported = _imported_modules((OPEN_POSITION_RESOLVER,))

    forbidden_prefixes = (
        "httpx",
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
