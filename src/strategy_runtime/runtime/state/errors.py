"""Typed runtime-state repository failures."""


class StrategyInstanceStateError(RuntimeError):
    code = "strategy_instance_state_error"


class StrategyInstanceIdentityConflict(StrategyInstanceStateError):
    code = "strategy_instance_identity_conflict"


class StrategyInstanceRegistrationConflict(StrategyInstanceStateError):
    code = "strategy_instance_registration_conflict"


class StrategyInstanceStateNotFound(StrategyInstanceStateError):
    code = "strategy_instance_state_not_found"
