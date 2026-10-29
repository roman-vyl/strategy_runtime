"""Refusals of an operator command; `status_code` and `reason` are the HTTP answer."""

from strategy_runtime.runtime.enabled_control.errors import EnabledControlRefused


class NoPosition(EnabledControlRefused):
    status_code = 409
    reason = "no_position"
