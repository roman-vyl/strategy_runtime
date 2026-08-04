"""Scope guardrails for the HTTP adapter layer.

Static source checks proving `adapters/http/app.py` has no direct route to
Runtime state -- no repository, no mutex registry, no domain transition --
beyond the single injected `process_first_fill` callable. Complements the
behavioral capturing-callable tests in
`tests/integration/http/test_first_fill_endpoint.py`.
"""

from __future__ import annotations

from pathlib import Path

_APP_SOURCE = Path("src/strategy_runtime/adapters/http/app.py").read_text(encoding="utf-8")


def test_http_app_has_no_direct_repository_mutex_or_domain_transition_access() -> None:
    forbidden_tokens = (
        "StrategyInstanceRuntimeStateRepository",
        "StrategyInstanceKeyedMutexRegistry",
        "apply_first_fill",
    )
    for token in forbidden_tokens:
        assert token not in _APP_SOURCE, f"forbidden token '{token}' found in adapters/http/app.py"
