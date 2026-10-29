"""The single place that freezes a first fill under the configured entry-order policy."""

from typing import Literal

from strategy_runtime.runtime.first_fill.state_applier import apply_first_fill
from strategy_runtime.runtime.state.models import StrategyInstanceRuntimeState

LiveEntryMode = Literal["ema_anchor", "touch_trigger"]
_LIVE_ENTRY_MODES: tuple[LiveEntryMode, ...] = ("ema_anchor", "touch_trigger")


class FirstFillFreezer:
    """Freeze the executed entry context, with the entry order's lifetime boundary in
    touch_trigger, atomically with the freeze itself.

    Every path that observes a first fill uses this one freezer; none of them knows the
    lifetime policy. The boundary is computed once here and stored in the frozen context,
    so a restart or a later config change never moves it.
    """

    def __init__(
        self,
        *,
        live_entry_mode: LiveEntryMode = "ema_anchor",
        order_lifetime_bars: int | None = None,
    ) -> None:
        if live_entry_mode not in _LIVE_ENTRY_MODES:
            raise ValueError(f"live_entry_mode must be one of {', '.join(_LIVE_ENTRY_MODES)}")
        if live_entry_mode == "touch_trigger" and (
            type(order_lifetime_bars) is not int or order_lifetime_bars < 0
        ):
            raise ValueError("touch_trigger requires order_lifetime_bars as an integer >= 0")
        self._order_lifetime_bars = (
            order_lifetime_bars if live_entry_mode == "touch_trigger" else None
        )

    def freeze(
        self,
        state: StrategyInstanceRuntimeState,
        trade_cycle_id: str,
        first_fill_at_ms: int,
    ) -> StrategyInstanceRuntimeState:
        """Same contract as `apply_first_fill`; returns `state` itself when already frozen."""
        return apply_first_fill(
            state,
            trade_cycle_id,
            first_fill_at_ms,
            order_lifetime_bars=self._order_lifetime_bars,
        )
