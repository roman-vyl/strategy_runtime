"""Failures of the trade-state read."""


class TradingStateError(RuntimeError):
    code = "trading_state_error"


class CatalogUnavailable(TradingStateError):
    code = "catalog_unavailable"


class StateUnavailable(TradingStateError):
    code = "state_unavailable"
