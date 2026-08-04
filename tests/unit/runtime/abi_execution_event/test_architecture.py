"""Scope guardrails for AbiExecutionEventOrchestrator.

Static source checks proving the capability's "no new business logic, no
Engine/ABI/sibling-orchestrator collaborator" boundary, complementing the
behavioral tests in test_orchestrator.py.
"""

from __future__ import annotations

from pathlib import Path

_ORCHESTRATOR_SOURCE = Path(
    "src/strategy_runtime/runtime/abi_execution_event/orchestrator.py"
).read_text(encoding="utf-8")


def test_orchestrator_delegates_to_the_existing_domain_transition_and_error() -> None:
    assert "apply_first_fill" in _ORCHESTRATOR_SOURCE
    assert "StrategyInstanceStateNotFound" in _ORCHESTRATOR_SOURCE
    assert "StrategyInstanceKeyedMutexRegistry" in _ORCHESTRATOR_SOURCE
    assert "StrategyInstanceRuntimeStateRepository" in _ORCHESTRATOR_SOURCE


def test_orchestrator_introduces_no_normalization_or_new_business_logic() -> None:
    forbidden_tokens = (
        "align_first_fill_to_entry_bar",
        "FrozenExecutedEntryContext",
        "get_or_create",
        "base_timeframe",
    )
    for token in forbidden_tokens:
        assert token not in _ORCHESTRATOR_SOURCE, (
            f"forbidden token '{token}' found in AbiExecutionEventOrchestrator"
        )


def test_orchestrator_has_no_engine_abi_or_sibling_orchestrator_collaborator() -> None:
    forbidden_tokens = (
        "StrategyRuntimeOrchestrator",
        "EntryReconciliationOrchestrator",
        "StrategyEngine",
        "httpx",
        "OpenPositionResolver",
        "StrategyUseCaseRouter",
    )
    for token in forbidden_tokens:
        assert token not in _ORCHESTRATOR_SOURCE, (
            f"forbidden token '{token}' found in AbiExecutionEventOrchestrator"
        )
