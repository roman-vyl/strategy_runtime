"""Typed execution failure for the entry-reconciliation execution bridge."""

from strategy_runtime.runtime.abi.entry_package_models import EntryPackagePublicError


class EntryReconciliationExecutionError(RuntimeError):
    """An ABI entry-package call did not produce a confirmed outcome.

    `public_error` is set directly from a returned `EntryPackagePublicError`
    result value (no `__cause__`, nothing was caught or re-raised); every other
    branch is raised with `from <original exception>` and leaves `public_error`
    unset.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        public_error: EntryPackagePublicError | None = None,
    ) -> None:
        if message is None:
            message = (
                f"ABI entry-package public error: {public_error.code}"
                if public_error is not None
                else "ABI entry-package execution failed"
            )
        super().__init__(message)
        self.public_error = public_error
