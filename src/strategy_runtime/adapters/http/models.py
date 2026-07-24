"""HTTP request and response models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class ClosedBarRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    instrument: str
    timeframe: str
    open_time_ms: Annotated[StrictInt, Field(ge=0)]

    @field_validator("instrument", "timeframe")
    @classmethod
    def require_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class AcceptedResponse(BaseModel):
    status: Literal["accepted"] = "accepted"


class LiveResponse(BaseModel):
    status: Literal["live"] = "live"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


class NotReadyResponse(BaseModel):
    status: Literal["not_ready"] = "not_ready"


class RejectedResponse(BaseModel):
    status: Literal["rejected"] = "rejected"
    reason: Literal["invalid_webhook"] = "invalid_webhook"
