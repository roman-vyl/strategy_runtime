"""Scope guardrails for the HTTP adapter layer.

Import-graph checks prove `adapters/http/app.py` has no direct route to
Runtime state -- no repository, no mutex registry, no domain transition --
beyond the single injected `process_first_fill` callable. Complements the
behavioral capturing-callable tests in
`tests/integration/http/test_first_fill_endpoint.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path("src/strategy_runtime/adapters/http/app.py")


def test_http_app_has_no_direct_repository_mutex_or_domain_transition_access() -> None:
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_prefixes = (
        "strategy_runtime.infrastructure",
        "strategy_runtime.runtime.coordination",
        "strategy_runtime.runtime.first_fill.state_applier",
        "strategy_runtime.runtime.state.repository",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )
