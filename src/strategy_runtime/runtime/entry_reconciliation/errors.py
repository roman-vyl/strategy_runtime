"""Domain errors for pure desired-entry reconciliation."""


class EntryReconciliationInvariantError(RuntimeError):
    """A command or formal success contradicts the expected domain transition."""
