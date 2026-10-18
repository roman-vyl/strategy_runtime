"""Semantic Strategy Runtime orchestrator through final aggregate application."""

from dataclasses import asdict, replace

from strategy_runtime.runtime.coordination import StrategyInstanceKeyedMutexRegistry
from strategy_runtime.runtime.entry_reconciliation_orchestrator import (
    EntryReconciliationOrchestrator,
)
from strategy_runtime.runtime.first_fill.errors import FirstFillInvariantError
from strategy_runtime.runtime.first_fill.journal import (
    TradeCycleOpenedJournalPort,
    journal_trade_cycle_opened,
)
from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.open_position.models import (
    PositionResolvedStrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.open_position.ports import OpenPositionResolverPort
from strategy_runtime.runtime.orchestrator.errors import UnknownStrategyProjectionError
from strategy_runtime.runtime.orchestrator.ports import LiveEntryEvaluationJournalPort
from strategy_runtime.runtime.position_management_execution import (
    apply_detected_trade_cycle_closure,
)
from strategy_runtime.runtime.position_management_orchestrator import (
    PositionManagementOrchestrator,
)
from strategy_runtime.runtime.routing.models import (
    LiveEntryProjectedStrategyInstance,
    OpenTradeProjectedStrategyInstance,
    PositionResolvedStrategyInstance,
)
from strategy_runtime.runtime.routing.ports import StrategyUseCaseRouterPort
from strategy_runtime.runtime.state.models import (
    GetOrCreateStrategyInstanceRuntimeStateRequest,
    StrategyInstanceRuntimeState,
)
from strategy_runtime.runtime.state.repository import StrategyInstanceRuntimeStateRepository
from strategy_runtime.runtime.trade_cycle_closure import (
    TradeCycleClosedJournalPort,
    TradeCycleClosure,
    journal_trade_cycle_closed,
)
from strategy_runtime.utility.committed_bar.models import (
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)
from strategy_runtime.utility.deployment_catalog.models import DeploymentSpecification


class StrategyRuntimeOrchestrator:
    def __init__(
        self,
        *,
        state_repository: StrategyInstanceRuntimeStateRepository,
        open_position_resolver: OpenPositionResolverPort,
        use_case_router: StrategyUseCaseRouterPort,
        keyed_mutex_registry: StrategyInstanceKeyedMutexRegistry,
        entry_reconciliation_orchestrator: EntryReconciliationOrchestrator,
        position_management_orchestrator: PositionManagementOrchestrator,
        live_entry_journal: LiveEntryEvaluationJournalPort | None = None,
        trade_cycle_closed_journal: TradeCycleClosedJournalPort | None = None,
        trade_cycle_opened_journal: TradeCycleOpenedJournalPort | None = None,
    ) -> None:
        self._state_repository = state_repository
        self._open_position_resolver = open_position_resolver
        self._use_case_router = use_case_router
        self._keyed_mutex_registry = keyed_mutex_registry
        self._entry_reconciliation_orchestrator = entry_reconciliation_orchestrator
        self._position_management_orchestrator = position_management_orchestrator
        self._live_entry_journal = live_entry_journal
        self._trade_cycle_closed_journal = trade_cycle_closed_journal
        self._trade_cycle_opened_journal = trade_cycle_opened_journal

    def process(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyInstanceRuntimeState:
        with self._keyed_mutex_registry.hold(unit.strategy_instance_id):
            state = self._state_repository.get_or_create(
                GetOrCreateStrategyInstanceRuntimeStateRequest(
                    strategy_instance_id=unit.strategy_instance_id,
                    strategy_id=unit.deployment.strategy_id,
                    instrument=unit.deployment.instrument,
                    base_timeframe=unit.deployment.base_timeframe,
                    raw_spec=unit.deployment.raw_spec,
                    source_path=unit.deployment.source_path,
                )
            )
            if state.pending_entry_recovery is not None or state.pending_close_recovery is not None:
                return state
            resolved = self._open_position_resolver.resolve(state)
            if resolved.closure is not None:
                # ABI proved the cycle ended on its own orders: end it before
                # Engine, and place no entry on this bar.
                saved_state = self._state_repository.save(
                    apply_detected_trade_cycle_closure(state, resolved.closure)
                )
                journal_trade_cycle_closed(
                    self._trade_cycle_closed_journal,
                    resolved.closure,
                    unit.committed_bar.open_time_ms,
                )
                return saved_state
            if resolved.position_open:
                resolved = self._ensure_first_fill_frozen(resolved, unit.committed_bar.open_time_ms)
                current_cycle = resolved.runtime_state.current_trade_cycle
                assert current_cycle is not None
                frozen_context = current_cycle.frozen_entry_context
                assert frozen_context is not None
                if frozen_context.entry_bar_open_time_ms > unit.committed_bar.open_time_ms:
                    return resolved.runtime_state
            projection = self._use_case_router.route(
                PositionResolvedStrategyInstance(unit, resolved)
            )
            closure: TradeCycleClosure | None = None

            if type(projection) is LiveEntryProjectedStrategyInstance:
                source_state = projection.source.resolved_state.runtime_state
                self._journal_live_entry(unit, projection)
                resulting_state = self._entry_reconciliation_orchestrator.execute(projection)
            elif type(projection) is OpenTradeProjectedStrategyInstance:
                source_state = projection.source.resolved_state.runtime_state
                resulting_state, closure = (
                    self._position_management_orchestrator.execute_with_closure(projection)
                )
            else:
                raise UnknownStrategyProjectionError

            if resulting_state == source_state:
                return resulting_state
            saved_state = self._state_repository.save(resulting_state)
            if closure is not None:
                journal_trade_cycle_closed(
                    self._trade_cycle_closed_journal, closure, unit.committed_bar.open_time_ms
                )
            return saved_state

    def dispatch(
        self, unit: StrategyBarProcessingUnit[DeploymentSpecification]
    ) -> StrategyCycleDispatchOutcome:
        self.process(unit)
        return StrategyCycleDispatchOutcome.succeeded(unit.strategy_instance_id)

    def _journal_live_entry(
        self,
        unit: StrategyBarProcessingUnit[DeploymentSpecification],
        projection: LiveEntryProjectedStrategyInstance,
    ) -> None:
        if self._live_entry_journal is None:
            return
        self._live_entry_journal.live_entry_evaluated(
            strategy_instance_id=unit.strategy_instance_id,
            instrument=unit.deployment.instrument,
            timeframe=unit.deployment.base_timeframe,
            bar_open_time_ms=unit.committed_bar.open_time_ms,
            desired_entry=(
                None if projection.desired_entry is None else asdict(projection.desired_entry)
            ),
        )

    def _ensure_first_fill_frozen(
        self, resolved: PositionResolvedStrategyInstanceRuntimeState, bar_open_time_ms: int
    ) -> PositionResolvedStrategyInstanceRuntimeState:
        state = resolved.runtime_state
        current_cycle = state.current_trade_cycle
        if current_cycle is None:
            raise FirstFillInvariantError(
                "apply_first_fill requires an existing current trade cycle"
            )
        assert resolved.first_fill_at_ms is not None
        resulting_state = apply_first_fill(
            state, current_cycle.trade_cycle_id, resolved.first_fill_at_ms
        )
        if resulting_state is state:
            # Already frozen: a repeated observation, not a new transition.
            return resolved
        saved_state = self._state_repository.save(resulting_state)
        assert resolved.average_entry_price is not None
        assert resolved.entry_order_link_id is not None
        journal_trade_cycle_opened(
            self._trade_cycle_opened_journal,
            strategy_instance_id=state.strategy_instance_id,
            trade_cycle_id=current_cycle.trade_cycle_id,
            bar_open_time_ms=bar_open_time_ms,
            first_fill_at_ms=resolved.first_fill_at_ms,
            average_entry_price=resolved.average_entry_price,
            entry_order_link_id=resolved.entry_order_link_id,
            entry_order_id=resolved.entry_order_id,
        )
        return replace(resolved, runtime_state=saved_state)
