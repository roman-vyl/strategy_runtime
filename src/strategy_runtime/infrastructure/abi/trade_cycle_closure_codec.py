"""Strict decoding of ABI's `closure` object, shared by the lookup and close codecs."""

from typing import cast

from strategy_runtime.runtime.trade_cycle_closure import TradeCycleClosure

CLOSURE_FIELD = "closure"
_CLOSURE_FIELDS = frozenset(
    {
        "strategy_instance_id",
        "trade_cycle_id",
        "reason",
        "order_id",
        "order_link_id",
        "parent_order_link_id",
    }
)


def decode_optional_closure(body: dict[str, object]) -> TradeCycleClosure | None:
    """Decode `closure` from a success body; a missing key or `null` means no closure.

    Raises TypeError/ValueError on any other shape.
    """
    if CLOSURE_FIELD not in body:
        return None
    value = body[CLOSURE_FIELD]
    if value is None:
        return None
    if type(value) is not dict:
        raise TypeError("closure must be a JSON object or null")
    closure = cast("dict[str, object]", value)
    actual = frozenset(closure)
    if actual != _CLOSURE_FIELDS:
        missing = sorted(_CLOSURE_FIELDS - actual)
        unknown = sorted(actual - _CLOSURE_FIELDS)
        raise ValueError(f"closure fields differ; missing={missing}, unknown={unknown}")
    for name in ("strategy_instance_id", "trade_cycle_id", "reason", "order_id"):
        if type(closure[name]) is not str:
            raise TypeError(f"closure.{name} must be a string")
    for name in ("order_link_id", "parent_order_link_id"):
        if closure[name] is not None and type(closure[name]) is not str:
            raise TypeError(f"closure.{name} must be a string or null")
    return TradeCycleClosure(
        strategy_instance_id=cast(str, closure["strategy_instance_id"]),
        trade_cycle_id=cast(str, closure["trade_cycle_id"]),
        reason=cast(str, closure["reason"]),
        order_id=cast(str, closure["order_id"]),
        order_link_id=cast("str | None", closure["order_link_id"]),
        parent_order_link_id=cast("str | None", closure["parent_order_link_id"]),
    )
