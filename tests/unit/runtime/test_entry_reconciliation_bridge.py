from collections.abc import Callable

import pytest

from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageProtocolError,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackageInternalError,
    EntryPackageRequest,
    EntryPackageResult,
    EntryPackageWireDesiredEntry,
)
from strategy_runtime.runtime.entry_reconciliation.models import (
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
)
from strategy_runtime.runtime.entry_reconciliation_bridge.bridge import (
    AbiEntryPackageExecutionBridge,
)
from strategy_runtime.runtime.entry_reconciliation_bridge.errors import (
    EntryReconciliationExecutionError,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import (
    RegisteredSpecSnapshot,
    StrategyInstanceRuntimeState,
)

ResultFactory = Callable[[EntryPackageRequest], EntryPackageResult]


class FakeAbiEntryPackagePort:
    def __init__(
        self,
        *,
        result_factory: ResultFactory | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self.requests: list[EntryPackageRequest] = []
        self._result_factory = result_factory
        self._raise_exc = raise_exc

    def send(self, request: EntryPackageRequest) -> EntryPackageResult:
        self.requests.append(request)
        if self._raise_exc is not None:
            raise self._raise_exc
        assert self._result_factory is not None
        return self._result_factory(request)


def test_present_command_maps_to_present_request_with_sourced_risk_multiplier() -> None:
    command = make_command(desired_entry=make_desired_entry())
    source_state = make_source_state(risk_multiplier="1.5")
    fake = FakeAbiEntryPackagePort(result_factory=lambda req: applied_result(req))

    bridge = AbiEntryPackageExecutionBridge(fake)
    result = bridge.execute(command, source_state)

    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent.strategy_instance_id == command.strategy_instance_id
    assert sent.trade_cycle_id == command.trade_cycle_id
    assert sent.ticker == command.ticker
    assert sent.risk_multiplier == "1.5"
    assert sent.desired_entry == EntryPackageWireDesiredEntry(
        side="long",
        source_plan_bar_open_time_ms=1785000000000,
        planned_entry_price="-123",
        initial_stop_price="999",
        initial_take_price="1",
        locked_exit_profile="default",
    )
    assert isinstance(result, EntryAppliedConfirmation)


def test_absent_command_maps_to_absent_request_with_sourced_risk_multiplier() -> None:
    command = make_command(desired_entry=None)
    source_state = make_source_state(risk_multiplier="2")
    fake = FakeAbiEntryPackagePort(
        result_factory=lambda req: EntryPackageAbsent(
            strategy_instance_id=req.strategy_instance_id,
            trade_cycle_id=req.trade_cycle_id,
        )
    )

    bridge = AbiEntryPackageExecutionBridge(fake)
    result = bridge.execute(command, source_state)

    sent = fake.requests[0]
    assert sent.desired_entry is None
    assert sent.risk_multiplier == "2"
    assert isinstance(result, EntryAbsentConfirmation)


def test_risk_multiplier_never_read_from_command() -> None:
    command = make_command(desired_entry=None)
    assert not hasattr(command, "risk_multiplier")
    source_state = make_source_state(risk_multiplier="3.25")
    fake = FakeAbiEntryPackagePort(
        result_factory=lambda req: EntryPackageAbsent(
            strategy_instance_id=req.strategy_instance_id,
            trade_cycle_id=req.trade_cycle_id,
        )
    )

    AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert fake.requests[0].risk_multiplier == "3.25"


def test_applied_result_maps_to_applied_confirmation_with_domain_desired_entry() -> None:
    command = make_command(desired_entry=make_desired_entry())
    source_state = make_source_state()
    fake = FakeAbiEntryPackagePort(result_factory=lambda req: applied_result(req))

    result = AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert isinstance(result, EntryAppliedConfirmation)
    assert result.strategy_instance_id == command.strategy_instance_id
    assert result.trade_cycle_id == command.trade_cycle_id
    assert result.applied_desired_entry == make_desired_entry()
    assert result.calculated_quantity == "0.00100"


def test_absent_result_maps_to_absent_confirmation() -> None:
    command = make_command(desired_entry=None)
    source_state = make_source_state()
    fake = FakeAbiEntryPackagePort(
        result_factory=lambda req: EntryPackageAbsent(
            strategy_instance_id=req.strategy_instance_id,
            trade_cycle_id=req.trade_cycle_id,
        )
    )

    result = AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert result == EntryAbsentConfirmation(
        strategy_instance_id=command.strategy_instance_id,
        trade_cycle_id=command.trade_cycle_id,
    )


def test_public_error_result_produces_execution_error_without_cause() -> None:
    command = make_command(desired_entry=None)
    source_state = make_source_state()
    public_error = EntryPackageInternalError(message="ABI internal error")
    fake = FakeAbiEntryPackagePort(result_factory=lambda _req: public_error)

    with pytest.raises(EntryReconciliationExecutionError) as raised:
        AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert raised.value.public_error is public_error
    assert raised.value.__cause__ is None
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "exc",
    [
        AbiEntryPackageTimeout("timed out"),
        AbiEntryPackageNetworkFailure("network failed"),
        AbiEntryPackageProtocolError("bad response"),
    ],
)
def test_raised_abi_exceptions_are_preserved_as_cause(exc: BaseException) -> None:
    command = make_command(desired_entry=None)
    source_state = make_source_state()
    fake = FakeAbiEntryPackagePort(raise_exc=exc)

    with pytest.raises(EntryReconciliationExecutionError) as raised:
        AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert raised.value.__cause__ is exc
    assert raised.value.public_error is None
    assert len(fake.requests) == 1


def test_send_is_called_exactly_once_and_never_retried() -> None:
    command = make_command(desired_entry=None)
    source_state = make_source_state()
    fake = FakeAbiEntryPackagePort(raise_exc=AbiEntryPackageTimeout("timed out"))

    with pytest.raises(EntryReconciliationExecutionError):
        AbiEntryPackageExecutionBridge(fake).execute(command, source_state)
    with pytest.raises(EntryReconciliationExecutionError):
        AbiEntryPackageExecutionBridge(fake).execute(command, source_state)

    assert len(fake.requests) == 2


def make_command(*, desired_entry: DesiredEntry | None) -> EntryReconciliationCommand:
    return EntryReconciliationCommand(
        strategy_instance_id="ema_pullback:abc",
        trade_cycle_id="cycle-1",
        ticker="BTCUSDT.P",
        desired_entry=desired_entry,
    )


def make_source_state(*, risk_multiplier: str = "1") -> StrategyInstanceRuntimeState:
    return StrategyInstanceRuntimeState(
        strategy_instance_id="ema_pullback:abc",
        strategy_id="ema_pullback",
        registered_spec_snapshot=RegisteredSpecSnapshot(
            instrument="BTCUSDT.P",
            base_timeframe="5m",
            raw_spec={"kind": "ema_pullback"},
            source_path="specs/ema_pullback.yaml",
        ),
        risk_multiplier=risk_multiplier,
    )


def make_desired_entry() -> DesiredEntry:
    return DesiredEntry(
        side="long",
        source_plan_bar_open_time_ms=1785000000000,
        planned_entry_price="-123",
        initial_stop_price="999",
        initial_take_price="1",
        locked_exit_profile="default",
    )


def applied_result(request: EntryPackageRequest) -> EntryPackageApplied:
    assert request.desired_entry is not None
    return EntryPackageApplied(
        strategy_instance_id=request.strategy_instance_id,
        trade_cycle_id=request.trade_cycle_id,
        applied_desired_entry=request.desired_entry,
        calculated_quantity="0.00100",
    )
