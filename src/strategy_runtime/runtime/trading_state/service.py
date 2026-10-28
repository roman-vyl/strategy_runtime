"""Read-only view of the stored trade state of every accepted deployment.

Reads the catalog once and each instance's stored state once; writes nothing and calls neither
ABI, Strategy Engine nor the exchange. The answer is Runtime's state as of its last processed bar.
"""

from collections.abc import Callable

from strategy_runtime.runtime.state.errors import StrategyInstanceStateError
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.trading_state.errors import CatalogUnavailable, StateUnavailable
from strategy_runtime.runtime.trading_state.models import (
    ENTRY_PENDING,
    FLAT,
    IN_POSITION,
    RecoveryPending,
    StrategyInstanceTradingState,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentCatalogUnavailableError,
)


class StrategyTradingStateService:
    def __init__(
        self,
        *,
        load_snapshot: Callable[[], DeploymentCatalogSnapshot],
        state_repository: StrategyInstanceRuntimeStateRepository,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._state_repository = state_repository

    def list(self) -> tuple[StrategyInstanceTradingState, ...]:
        try:
            snapshot = self._load_snapshot()
        except DeploymentCatalogUnavailableError as exc:
            raise CatalogUnavailable from exc
        items: list[StrategyInstanceTradingState] = []
        for deployment in snapshot.accepted_deployments:
            try:
                state = self._state_repository.get(deployment.strategy_instance_id)
            except (StrategyInstanceStateError, OSError, ValueError) as exc:
                raise StateUnavailable from exc
            items.append(_describe(deployment.strategy_instance_id, state))
        return tuple(items)


def _describe(
    strategy_instance_id: str, state: StrategyInstanceRuntimeState | None
) -> StrategyInstanceTradingState:
    if state is None:
        return StrategyInstanceTradingState(strategy_instance_id, FLAT, None, None, None, None)
    recovery: RecoveryPending | None = None
    if state.pending_entry_recovery is not None:
        recovery = "entry"
    elif state.pending_close_recovery is not None:
        recovery = "close"
    cycle = state.current_trade_cycle
    if cycle is None:
        return StrategyInstanceTradingState(strategy_instance_id, FLAT, None, None, None, recovery)
    frozen = cycle.frozen_entry_context
    return StrategyInstanceTradingState(
        strategy_instance_id=strategy_instance_id,
        trade_state=ENTRY_PENDING if frozen is None else IN_POSITION,
        trade_cycle_id=cycle.trade_cycle_id,
        side=cycle.desired_entry.side,
        first_fill_at_ms=None if frozen is None else frozen.first_fill_at_ms,
        recovery_pending=recovery,
    )
