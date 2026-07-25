"""Transport-independent ABI entry-package port."""

from typing import Protocol

from strategy_runtime.runtime.abi.entry_package_models import (
    EntryPackageRequest,
    EntryPackageResult,
)


class AbiEntryPackagePort(Protocol):
    def send(self, request: EntryPackageRequest) -> EntryPackageResult: ...
