"""Typed error for the durable file-backed state repository."""


class StrategyInstanceStateReplayError(RuntimeError):
    """A durable state file failed replay: a fail-closed integrity violation.

    Raised for any line other than the file's last line that fails to parse
    as JSON, and for any line -- including the last line -- that parses as
    valid JSON but fails envelope/schema/domain validation. A JSON parse
    failure confined to the file's last line is not an error: it is
    silently tolerated as a truncated write left by a crash mid-append.
    """

    code = "strategy_instance_state_replay_error"
