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


def test_engine_adapters_are_wired_into_production_composition_by_i4d() -> None:
    """I4d composes both adapters into `build_application`, inverting the
    I4c-era guardrail that proved them implemented in isolation with zero
    production wiring. `runtime.engine.errors` remains unimported by these
    wired components: only the adapter classes themselves are constructed
    here, not the typed failure taxonomy, which callers catch through the
    existing `StrategyEngineProjectionUnavailable` supertype instead."""
    imported = _imported_modules(WIRED_COMPONENT_PATHS)

    assert any(
        name == "strategy_runtime.infrastructure.strategy_engine"
        or name.startswith("strategy_runtime.infrastructure.strategy_engine.")
        for name in imported
    )
    assert not any(
        name == "strategy_runtime.runtime.engine.errors"
        or name.startswith("strategy_runtime.runtime.engine.errors.")
        for name in imported
    )

    application_source = Path("src/strategy_runtime/bootstrap/application.py").read_text(
        encoding="utf-8"
    )
    for token in ("HttpxStrategyEngineLiveEntryAdapter", "HttpxStrategyEngineOpenTradeAdapter"):
        assert token in application_source, f"expected '{token}' in production composition"


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


def test_engine_adapters_do_not_depend_on_abi_entry_package_client() -> None:
    """The shared Engine wire codec/adapters have no dependency on the ABI
    entry-package client's transport-free models or codec. This does not
    assert anything about that client's own content, which a later I4c task
    may change independently."""
    engine_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in STRATEGY_ENGINE_INFRASTRUCTURE_PACKAGE.glob("*.py")
    )
    assert "entry_package_codec" not in engine_source
    assert "EntryPackageRequest" not in engine_source
    assert "EntryPackageResult" not in engine_source
