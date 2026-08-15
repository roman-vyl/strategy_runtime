"""Typed errors for the durable file-backed state repository."""


class StrategyInstanceStateReplayError(RuntimeError):
    """A durable state file failed replay: a fail-closed integrity violation.

    Raised for any line other than the file's last line that fails to parse
    as JSON, and for any line -- including the last line -- that parses as
    valid JSON but fails envelope/schema/domain validation. A JSON parse
    failure confined to the file's last line is not an error: it is
    silently tolerated as a truncated write left by a crash mid-append.
    """

    code = "strategy_instance_state_replay_error"


class StrategyInstanceStateStorePoisoned(RuntimeError):
    """The durable store's on-disk state is no longer trustworthy.

    Raised when a prior physical append (open/write/flush/`fsync`) failed
    partway, leaving an ambiguous on-disk outcome -- bytes may or may not
    have reached the file. Once poisoned, every subsequent `get_or_create`,
    `get`, and `save` call on this repository instance fails closed instead
    of continuing to serve from a not-provably-durable file; recovery
    requires restarting the process (a fresh repository instance replays
    the file from scratch). A failure before the physical write is
    attempted -- e.g. serialization -- does not poison the repository.
    """

    code = "strategy_instance_state_store_poisoned"
