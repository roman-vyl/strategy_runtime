"""Typed use-case routing and Engine projection failures."""


class StrategyProjectionError(RuntimeError):
    code = "strategy_projection_error"


class StrategyInstanceBindingError(StrategyProjectionError):
    code = "strategy_instance_binding_error"


class StrategyEngineProjectionUnavailable(StrategyProjectionError):
    code = "strategy_engine_projection_unavailable"


class EngineResponseBindingError(StrategyProjectionError):
    code = "engine_response_binding_error"


class OpenTradeContextUnavailable(StrategyProjectionError):
    code = "open_trade_context_unavailable"
