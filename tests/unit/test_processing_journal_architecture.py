import ast
from pathlib import Path

PACKAGE = Path("src/strategy_runtime/utility/processing_journal")


def test_processing_journal_has_no_forbidden_imports() -> None:
    paths = tuple(PACKAGE.glob("*.py"))
    assert paths
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    forbidden_prefixes = (
        "fastapi",
        "httpx",
        "strategy_runtime.adapters",
        "strategy_runtime.bootstrap",
        "strategy_runtime.config",
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime",
        "strategy_runtime.utility.deployment_catalog",
        "strategy_runtime.utility.deployment_selection",
        "strategy_runtime.infrastructure.strategy_engine",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
