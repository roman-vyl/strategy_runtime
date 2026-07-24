"""Factories for runtime correlation identifiers and timestamps."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

IdentifierFactory = Callable[[], str]
TimestampFactory = Callable[[], str]


def new_identifier() -> str:
    """Return a new opaque identifier suitable for flow and event correlation."""

    return str(uuid4())


def utc_timestamp() -> str:
    """Return a current ISO-8601 UTC timestamp."""

    return datetime.now(UTC).isoformat()
