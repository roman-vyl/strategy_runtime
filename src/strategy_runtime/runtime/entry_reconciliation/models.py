"""Transport-free values used by pure desired-entry reconciliation."""

from dataclasses import dataclass

from strategy_runtime.runtime.recipes.entry import DesiredEntry
from strategy_runtime.shared.decimal_text import is_exact_decimal_text


@dataclass(frozen=True, slots=True)
class NoOp:
    """No external entry-package change is required."""


@dataclass(frozen=True, slots=True)
class Apply:
    """Apply the first acknowledged desired entry."""

    desired_entry: DesiredEntry

    def __post_init__(self) -> None:
        _require_desired_entry(self.desired_entry, "desired_entry")


@dataclass(frozen=True, slots=True)
class Cancel:
    """Remove the package on an acknowledged current cycle."""

    trade_cycle_id: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")


@dataclass(frozen=True, slots=True)
class Replace:
    """Replace the package on an acknowledged current cycle with a new desired entry.

    A logical decision only: the orchestrator executes it as a confirmed
    ``Cancel`` of ``trade_cycle_id`` followed by an ``Apply`` of
    ``desired_entry`` under a newly reserved trade-cycle identity.
    """

    trade_cycle_id: str
    desired_entry: DesiredEntry

    def __post_init__(self) -> None:
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_entry(self.desired_entry, "desired_entry")


EntryReconciliationDecision = NoOp | Apply | Replace | Cancel


@dataclass(frozen=True, slots=True)
class EntryReconciliationCommand:
    """I3-owned command intent, independent from every client DTO."""

    strategy_instance_id: str
    trade_cycle_id: str
    ticker: str
    desired_entry: DesiredEntry | None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_non_empty_string(self.ticker, "ticker")
        if self.desired_entry is not None:
            _require_desired_entry(self.desired_entry, "desired_entry")


@dataclass(frozen=True, slots=True)
class EntryAppliedConfirmation:
    """Facts required to acknowledge a present entry package."""

    strategy_instance_id: str
    trade_cycle_id: str
    applied_desired_entry: DesiredEntry
    calculated_quantity: str
    trigger_price: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    quantity: str | None = None
    order_link_id: str | None = None
    order_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_desired_entry(self.applied_desired_entry, "applied_desired_entry")
        if not is_exact_decimal_text(self.calculated_quantity):
            raise ValueError("calculated_quantity must be exact-decimal text")
        for name in ("trigger_price", "stop_loss", "take_profit", "quantity"):
            value = getattr(self, name)
            if value is not None and not is_exact_decimal_text(value):
                raise ValueError(f"{name} must be exact-decimal text")
        for name in ("order_link_id", "order_id"):
            value = getattr(self, name)
            if value is not None:
                _require_non_empty_string(value, name)


@dataclass(frozen=True, slots=True)
class EntryAbsentConfirmation:
    """Facts required to acknowledge entry-package absence."""

    strategy_instance_id: str
    trade_cycle_id: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")


SuccessfulEntryConfirmation = EntryAppliedConfirmation | EntryAbsentConfirmation


@dataclass(frozen=True, slots=True)
class EntryDeclinedOutcome:
    """ABI refused an APPLY before contacting the exchange; no cycle exists."""

    strategy_instance_id: str
    trade_cycle_id: str
    decline_reason: str
    decline_message: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.strategy_instance_id, "strategy_instance_id")
        _require_non_empty_string(self.trade_cycle_id, "trade_cycle_id")
        _require_non_empty_string(self.decline_reason, "decline_reason")
        _require_non_empty_string(self.decline_message, "decline_message")


EntryExecutionOutcome = SuccessfulEntryConfirmation | EntryDeclinedOutcome


def _require_non_empty_string(value: str, name: str) -> None:
    if type(value) is not str or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty string")


def _require_desired_entry(value: DesiredEntry, name: str) -> None:
    if type(value) is not DesiredEntry:
        raise TypeError(f"{name} must be DesiredEntry")
