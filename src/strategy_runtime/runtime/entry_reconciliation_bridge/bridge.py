"""Pure translator from EntryReconciliationExecutionPort to AbiEntryPackagePort."""

from strategy_runtime.runtime.abi.entry_package_errors import (
    AbiEntryPackageNetworkFailure,
    AbiEntryPackageProtocolError,
    AbiEntryPackageTimeout,
)
from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageAbsent,
    EntryPackageApplied,
    EntryPackagePublicError,
    EntryPackageRequest,
    EntryPackageWireDesiredEntry,
)
from strategy_runtime.runtime.abi.entry_package_ports import AbiEntryPackagePort
from strategy_runtime.runtime.entry_reconciliation.models import (
    EntryAbsentConfirmation,
    EntryAppliedConfirmation,
    EntryReconciliationCommand,
    SuccessfulEntryConfirmation,
)
from strategy_runtime.runtime.entry_reconciliation_bridge.errors import (
    EntryReconciliationExecutionError,
)
from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState


class AbiEntryPackageExecutionBridge:
    """Translate one command + source_state into exactly one ABI entry-package call."""

    def __init__(self, abi_entry_package: AbiEntryPackagePort) -> None:
        self._abi_entry_package = abi_entry_package

    def execute(
        self,
        command: EntryReconciliationCommand,
        source_state: StrategyInstanceRuntimeState,
    ) -> SuccessfulEntryConfirmation:
        request = EntryPackageRequest(
            strategy_instance_id=command.strategy_instance_id,
            trade_cycle_id=command.trade_cycle_id,
            ticker=command.ticker,
            desired_entry=_encode_desired_entry(command.desired_entry),
            risk_multiplier=source_state.risk_multiplier,
        )

        try:
            result = self._abi_entry_package.send(request)
        except AbiEntryPackageTimeout as exc:
            raise EntryReconciliationExecutionError("ABI entry-package request timed out") from exc
        except AbiEntryPackageNetworkFailure as exc:
            raise EntryReconciliationExecutionError(
                "ABI entry-package network transport failed"
            ) from exc
        except AbiEntryPackageProtocolError as exc:
            raise EntryReconciliationExecutionError(
                "ABI entry-package response was invalid"
            ) from exc

        if type(result) is EntryPackageApplied:
            return EntryAppliedConfirmation(
                strategy_instance_id=result.strategy_instance_id,
                trade_cycle_id=result.trade_cycle_id,
                applied_desired_entry=_decode_desired_entry(result.applied_desired_entry),
                calculated_quantity=result.calculated_quantity,
            )
        if type(result) is EntryPackageAbsent:
            return EntryAbsentConfirmation(
                strategy_instance_id=result.strategy_instance_id,
                trade_cycle_id=result.trade_cycle_id,
            )
        if isinstance(result, EntryPackagePublicError):
            raise EntryReconciliationExecutionError(public_error=result)
        raise EntryReconciliationExecutionError(
            f"ABI entry-package returned an unrecognized result: {type(result)!r}"
        )


def _encode_desired_entry(value: DesiredEntry | None) -> EntryPackageWireDesiredEntry | None:
    if value is None:
        return None
    return EntryPackageWireDesiredEntry(
        side=value.side,
        source_plan_bar_open_time_ms=value.source_plan_bar_open_time_ms,
        planned_entry_price=value.planned_entry_price,
        initial_stop_price=value.initial_stop_price,
        initial_take_price=value.initial_take_price,
        locked_exit_profile=value.locked_exit_profile,
    )


def _decode_desired_entry(value: EntryPackageWireDesiredEntry) -> DesiredEntry:
    return DesiredEntry(
        side=value.side,
        source_plan_bar_open_time_ms=value.source_plan_bar_open_time_ms,
        planned_entry_price=value.planned_entry_price,
        initial_stop_price=value.initial_stop_price,
        initial_take_price=value.initial_take_price,
        locked_exit_profile=value.locked_exit_profile,
    )
