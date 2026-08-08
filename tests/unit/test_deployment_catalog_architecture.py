import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "fastapi",
    "httpx",
    "strategy_runtime.adapters",
    "strategy_runtime.bootstrap",
    "strategy_runtime.config",
    "strategy_runtime.infrastructure",
    "strategy_runtime.runtime",
    "strategy_runtime.utility.committed_bar",
    "strategy_runtime.utility.deployment_selection",
    "strategy_runtime.utility.processing_journal",
)


def test_deployment_catalog_has_no_forbidden_dependencies() -> None:
    paths = tuple(Path("src/strategy_runtime/utility/deployment_catalog").rglob("*.py"))
    assert paths
    imported: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in FORBIDDEN_PREFIXES
    )
