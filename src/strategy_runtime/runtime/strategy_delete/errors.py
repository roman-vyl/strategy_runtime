"""Refusals specific to a delete; the shared ones come from `enabled_control.errors`."""

from strategy_runtime.runtime.enabled_control.errors import EnabledControlRefused


class StillEnabled(EnabledControlRefused):
    status_code = 409
    reason = "still_enabled"


class TrashNameTaken(EnabledControlRefused):
    status_code = 409
    reason = "trash_name_taken"


class MoveFailed(EnabledControlRefused):
    status_code = 500
    reason = "move_failed"
