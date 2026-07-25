"""Typed failures for an unconfirmed ABI entry-package call."""


class AbiEntryPackageClientError(RuntimeError):
    """Base class for entry-package failures that produce no valid ABI result."""

    code = "abi_entry_package_client_error"


class AbiEntryPackageTimeout(AbiEntryPackageClientError):
    """The single bounded HTTP attempt timed out."""

    code = "abi_entry_package_timeout"


class AbiEntryPackageNetworkFailure(AbiEntryPackageClientError):
    """A non-timeout network transport failure prevented a valid response."""

    code = "abi_entry_package_network_failure"


class AbiEntryPackageProtocolError(AbiEntryPackageClientError):
    """ABI returned a response outside the approved public HTTP contract."""

    code = "abi_entry_package_protocol_error"
