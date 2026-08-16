"""Typed failures for an inconclusive ABI entry-cycle recovery-state query."""


class AbiEntryCycleRecoveryClientError(RuntimeError):
    """Base class for recovery-state failures that produce no valid ABI result."""

    code = "abi_entry_cycle_recovery_client_error"


class AbiEntryCycleRecoveryTimeout(AbiEntryCycleRecoveryClientError):
    """The single bounded HTTP attempt timed out."""

    code = "abi_entry_cycle_recovery_timeout"


class AbiEntryCycleRecoveryNetworkFailure(AbiEntryCycleRecoveryClientError):
    """A non-timeout network transport failure prevented a valid response."""

    code = "abi_entry_cycle_recovery_network_failure"


class AbiEntryCycleRecoveryProtocolError(AbiEntryCycleRecoveryClientError):
    """ABI returned a response outside the approved public HTTP contract."""

    code = "abi_entry_cycle_recovery_protocol_error"


class AbiEntryCycleRecoveryUnavailable(AbiEntryCycleRecoveryClientError):
    """A documented 500 internal_error: a genuine query failure or insufficient
    positive evidence to establish any recovery_state -- the two are
    indistinguishable to Runtime and treated identically (see design.md
    Decision 4: absence of evidence is never treated as evidence of absence)."""

    code = "abi_entry_cycle_recovery_unavailable"


class AbiEntryCycleRecoveryUnknownTradeCycleBinding(AbiEntryCycleRecoveryClientError):
    """A documented 422 unknown_trade_cycle_binding: distinct from every
    recovery_state, and never inferred as terminal_without_fill."""

    code = "abi_entry_cycle_recovery_unknown_trade_cycle_binding"
