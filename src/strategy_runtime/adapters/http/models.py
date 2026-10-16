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


class FirstFillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    first_fill_at_ms: Annotated[StrictInt, Field(gt=0)]


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


class FirstFillRecordedResponse(BaseModel):
    status: Literal["first_fill_recorded"] = "first_fill_recorded"


class StrategyInstanceStateNotFoundResponse(BaseModel):
    status: Literal["strategy_instance_state_not_found"] = "strategy_instance_state_not_found"


class FirstFillConflictResponse(BaseModel):
    status: Literal["first_fill_conflict"] = "first_fill_conflict"


class InternalErrorResponse(BaseModel):
    status: Literal["internal_error"] = "internal_error"


class CatalogUnavailableResponse(BaseModel):
    status: Literal["catalog_unavailable"] = "catalog_unavailable"


class StrategyInstanceItem(BaseModel):
    strategy_instance_id: str
    strategy_id: str
    instrument: str
    base_timeframe: str
    enabled: bool
    source_path: str


class InvalidDeploymentFileItem(BaseModel):
    source_path: str
    error_code: str
    error_message: str | None


class DuplicateDeploymentIdentityItem(BaseModel):
    strategy_instance_id: str
    source_paths: list[str]


class StrategyInstanceListResponse(BaseModel):
    scanned_file_count: int
    strategy_instances: list[StrategyInstanceItem]
    invalid_files: list[InvalidDeploymentFileItem]
    duplicate_identities: list[DuplicateDeploymentIdentityItem]
