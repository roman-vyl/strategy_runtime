"""Domain errors for the pure first-fill transition."""


class FirstFillInvariantError(RuntimeError):
    """A first-fill call contradicts the expected domain transition."""
