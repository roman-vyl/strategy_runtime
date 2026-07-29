"""Architecture and scope guardrails for the ABI open-position HTTP adapter (I4c)."""

import ast
from pathlib import Path

ABI_INFRASTRUCTURE_PACKAGE = Path("src/strategy_runtime/infrastructure/abi")
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


def test_new_open_position_adapter_is_not_referenced_by_production_composition() -> None:
    imported = _imported_modules(WIRED_COMPONENT_PATHS)

    assert not any(
        name == "strategy_runtime.infrastructure.abi"
        or name.startswith("strategy_runtime.infrastructure.abi.")
        for name in imported
    )

    forbidden_tokens = ("HttpxAbiOpenPositionLookupAdapter",)
    source = "\n".join(path.read_text(encoding="utf-8") for path in WIRED_COMPONENT_PATHS)
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in production composition"


def test_new_open_position_adapter_module_has_no_forbidden_dependencies() -> None:
    assert tuple(ABI_INFRASTRUCTURE_PACKAGE.glob("*.py"))
    imported = _imported_modules(tuple(ABI_INFRASTRUCTURE_PACKAGE.glob("*.py")))

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


def test_existing_abi_entry_package_client_is_untouched_by_open_position_adapter() -> None:
    source_path = Path("src/strategy_runtime/runtime/abi/entry_package_codec.py")
    assert "accepted_risk_multiplier" in source_path.read_text(encoding="utf-8")

    open_position_source = "\n".join(
        path.read_text(encoding="utf-8") for path in ABI_INFRASTRUCTURE_PACKAGE.glob("*.py")
    )
    assert "entry_package_codec" not in open_position_source
    assert "EntryPackageRequest" not in open_position_source
    assert "EntryPackageResult" not in open_position_source


def test_open_position_resolver_is_unchanged_and_still_only_transport_free() -> None:
    """9.1 (scoped): OpenPositionResolver has no httpx/adapter/URL ownership."""
    source_path = Path("src/strategy_runtime/runtime/open_position/resolver.py")
    source = source_path.read_text(encoding="utf-8")

    forbidden_tokens = ("httpx", "HttpxAbiOpenPositionLookupAdapter", "base_url", "timeout_seconds")
    for token in forbidden_tokens:
        assert token not in source, f"forbidden token '{token}' found in resolver.py"
