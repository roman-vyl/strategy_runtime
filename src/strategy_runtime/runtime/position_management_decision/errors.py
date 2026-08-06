"""Domain errors for the pure position-management decision."""


class PositionManagementDecisionInvariantError(RuntimeError):
    """The current trade cycle's lifecycle state cannot yield a decision."""
