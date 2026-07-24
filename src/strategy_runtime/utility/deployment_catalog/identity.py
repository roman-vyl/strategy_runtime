"""Deterministic identity for one immutable strategy deployment."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_IDENTITY_PREFIX_SEPARATOR = ":"
_DIGEST_HEX_LENGTH = 24


def derive_strategy_instance_id(
    *,
    strategy_id: str,
    ticker: str,
    base_timeframe: str,
    raw_spec: Mapping[str, Any],
) -> str:
    """Derive stable identity from trading semantics and market coordinates.

    Formatting, JSON key order, source filename, and unrelated catalog metadata do
    not affect the result. Any semantic strategy, ticker, or timeframe change does.
    """

    identity_payload = {
        "strategy_id": strategy_id,
        "ticker": ticker,
        "base_timeframe": base_timeframe,
        "raw_spec": raw_spec,
    }
    canonical_payload = json.dumps(
        identity_payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_payload).hexdigest()[:_DIGEST_HEX_LENGTH]
    return f"{strategy_id}{_IDENTITY_PREFIX_SEPARATOR}{digest}"
