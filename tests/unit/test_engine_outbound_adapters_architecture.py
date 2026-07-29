"""Architecture and scope guardrails for the two new Engine HTTP adapters (I4c)."""

import ast
from pathlib import Path

STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE = Path("src/strategy_runtime/infrastructure/strategy_engine")
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


def test_new_engine_adapters_are_not_referenced_by_production_composition() -> None:
    imported = _imported_modules(WIRED_COMPONENT_PATHS)

    forbidden_prefixes = (
        "strategy_runtime.infrastructure.strategy_engine",
        "strategy_runtime.runtime.engine.errors",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )

    forbidden_tokens = (
        "HttpxStrategyEngineLiveEntryAdapter",
        "HttpxStrategyEngineOpenTradeAdapter",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in WIRED_COMPONENT_PATHS)
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in production composition"


def test_new_engine_adapters_module_has_no_forbidden_dependencies() -> None:
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
        "strategy_runtime.config",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )


def test_existing_abi_entry_package_client_is_unmodified_by_this_change() -> None:
    """9.3 (scoped): the shared Engine wire codec/adapters do not touch the
    archived ABI entry-package HTTP client module or its helpers."""
    engine_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE.glob("*.py")
    )
    assert "entry_package_codec" not in engine_source
    assert "EntryPackageRequest" not in engine_source
    assert "EntryPackageResult" not in engine_source
