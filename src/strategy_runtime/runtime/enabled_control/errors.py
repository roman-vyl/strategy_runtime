"""Typed refusals of an enabled change; `status_code` and `reason` are the HTTP answer."""


class EnabledControlRefused(RuntimeError):
    status_code = 500
    reason = "enabled_control_refused"

    def __init__(self) -> None:
        super().__init__(self.reason)


class StrategyInstanceNotFound(EnabledControlRefused):
    status_code = 404
    reason = "strategy_instance_not_found"


class InstanceBusy(EnabledControlRefused):
    status_code = 503
    reason = "instance_busy"


class RecoveryPending(EnabledControlRefused):
    status_code = 409
    reason = "recovery_pending"


class PositionOpen(EnabledControlRefused):
    status_code = 409
    reason = "position_open"


class CycleNotSettled(EnabledControlRefused):
    status_code = 409
    reason = "cycle_not_settled"


class CancelNotConfirmed(EnabledControlRefused):
    status_code = 409
    reason = "cancel_not_confirmed"


class AbiUnavailable(EnabledControlRefused):
    status_code = 502
    reason = "abi_unavailable"


class FileChanged(EnabledControlRefused):
    status_code = 409
    reason = "file_changed"


class IdentityChanged(EnabledControlRefused):
    status_code = 500
    reason = "identity_changed"


class WriteFailed(EnabledControlRefused):
    status_code = 500
    reason = "write_failed"


class CatalogUnavailable(EnabledControlRefused):
    status_code = 503
    reason = "catalog_unavailable"
