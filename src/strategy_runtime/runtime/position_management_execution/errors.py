"""Domain errors for position-management execution."""


class PositionManagementExecutionInvariantError(RuntimeError):
    """A command or confirmation contradicts the expected position-management transition."""
