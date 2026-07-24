import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "strategy_runtime.utility.committed_bar.orchestrator",
    "strategy_runtime.utility.activation",
    "strategy_runtime.adapters.activation",
    "strategy_runtime.adapters.strategy_engine",
    "strategy_runtime.ports.strategy_engine",
    "strategy_runtime.application.process_committed_bar",
    "fastapi",
    "strategy_runtime.domain.strategy_registry",
    "strategy_runtime.ports.strategy_registry",
    "strategy_runtime.adapters.strategy_registry",
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
