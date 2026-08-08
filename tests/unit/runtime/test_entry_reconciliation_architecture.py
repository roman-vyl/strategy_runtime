import ast
from pathlib import Path


def test_entry_reconciliation_has_only_approved_pure_dependencies() -> None:
    root = Path("src/strategy_runtime/runtime/entry_reconciliation")
    paths = tuple(root.glob("*.py"))
    assert paths
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    allowed_prefixes = (
        "dataclasses",
        "strategy_runtime.runtime.entry_reconciliation",
        "strategy_runtime.runtime.recipes.entry",
        "strategy_runtime.runtime.state.models",
        "strategy_runtime.shared.decimal_text",
    )
    assert all(
        any(name == prefix or name.startswith(f"{prefix}.") for prefix in allowed_prefixes)
        for name in imported
    )


def test_entry_reconciliation_does_not_know_client_or_orchestration_models() -> None:
    root = Path("src/strategy_runtime/runtime/entry_reconciliation")
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "EntryPackageRequest",
        "EntryPackageApplied",
        "EntryPackageAbsent",
        "AbiEntryPackagePort",
        "TradeCycleIdFactory",
        "entry_reconciliation_orchestrator",
        "repository",
        "keyed_mutex",
        "orchestrator",
        "fastapi",
        "httpx",
    )
    for token in forbidden:
        assert token not in text
