"""Transport-independent ABI entry-cycle recovery-state port."""

from typing import Protocol

from strategy_runtime.runtime.abi.entry_cycle_recovery_models import RecoveryStateResponse
from strategy_runtime.runtime.abi.entry_package_models import EntryPackageResult


class AbiEntryCycleRecoveryPort(Protocol):
    def query(self, strategy_instance_id: str, trade_cycle_id: str) -> RecoveryStateResponse: ...

    def cancel(
        self,
        strategy_instance_id: str,
        trade_cycle_id: str,
        ticker: str,
        risk_multiplier: str,
    ) -> EntryPackageResult: ...
