"""Future semantic runtime orchestration errors."""


class OpenTradeProjectionUnsupportedError(Exception):
    """Projection variant not yet supported in closed-bar orchestration."""


class UnknownStrategyProjectionError(Exception):
    """Projection runtime type not recognized by the orchestrator."""
