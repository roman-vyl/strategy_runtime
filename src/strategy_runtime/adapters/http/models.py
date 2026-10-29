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


class EnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool


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


class EnabledChangedResponse(BaseModel):
    strategy_instance_id: str
    enabled: bool
    cancelled_entry_order: bool


class EnabledChangeRefusedResponse(BaseModel):
    status: Literal["enabled_change_refused"] = "enabled_change_refused"
    reason: str


class DeletedResponse(BaseModel):
    strategy_instance_id: str
    deleted: Literal[True] = True
    cancelled_entry_order: bool
    trash_file: str


class DeleteRefusedResponse(BaseModel):
    status: Literal["delete_refused"] = "delete_refused"
    reason: str


class EmaStackEntryItem(BaseModel):
    role: str
    timeframe: str
    period: int
    source: str


class EpisodeEntryItem(BaseModel):
    episode_ref: str
    params: dict[str, int]


class ChartLayersResponse(BaseModel):
    strategy_instance_id: str
    ema_stack: list[EmaStackEntryItem]
    episodes: list[EpisodeEntryItem]


class ChartLayersRefusedResponse(BaseModel):
    status: Literal["chart_layers_refused"] = "chart_layers_refused"
    reason: str
    engine_code: str | None = None
    engine_message: str | None = None


class StrategyInstanceStateItem(BaseModel):
    strategy_instance_id: str
    trade_state: Literal["flat", "entry_pending", "in_position"]
    trade_cycle_id: str | None
    side: Literal["long", "short"] | None
    first_fill_at_ms: int | None
    recovery_pending: Literal["entry", "close"] | None


class StrategyInstanceStateListResponse(BaseModel):
    strategy_instances: list[StrategyInstanceStateItem]


class StateUnavailableResponse(BaseModel):
    status: Literal["state_unavailable"] = "state_unavailable"


class ClosePositionResponse(BaseModel):
    strategy_instance_id: str
    trade_cycle_id: str
    enabled: Literal[False] = False
    closure_reason: str | None


class CancelEntryOrdersResponse(BaseModel):
    strategy_instance_id: str
    enabled: Literal[False] = False
    cancelled_entry_order: bool
