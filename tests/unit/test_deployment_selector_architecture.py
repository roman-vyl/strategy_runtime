import ast
from pathlib import Path


def test_deployment_selector_has_no_forbidden_dependencies() -> None:
    root = Path("src/strategy_runtime/utility/deployment_selection")
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

    forbidden_prefixes = (
        "strategy_runtime.infrastructure",
        "strategy_runtime.adapters",
        "fastapi",
        "strategy_runtime.infrastructure.strategy_engine",
        "strategy_runtime.infrastructure.abi",
        "strategy_runtime.utility.processing_journal",
        "strategy_runtime.domain.strategy_registry",
        "strategy_runtime.utility.activation",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
