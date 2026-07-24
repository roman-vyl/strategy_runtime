"""Immutable application models owned by committed-bar orchestration."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class CommittedBarEvent:
    """One accepted market-data fact passed into application orchestration."""

    instrument: str
    timeframe: str
    open_time_ms: int

    def __post_init__(self) -> None:
        if not self.instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        if not self.timeframe.strip():
            raise ValueError("timeframe must be a non-empty string")
        if isinstance(self.open_time_ms, bool) or not isinstance(self.open_time_ms, int):
            raise TypeError("open_time_ms must be an integer")
        if self.open_time_ms < 0:
            raise ValueError("open_time_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class SelectedDeployment[DeploymentT]:
    """A deployment selected upstream and made deterministically orderable."""

    strategy_instance_id: str
    deployment: DeploymentT

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip():
            raise ValueError("strategy_instance_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class StrategyBarProcessingUnit[DeploymentT]:
    """One immutable unit handed to the later strategy-cycle capability."""

    strategy_instance_id: str
    deployment: DeploymentT
    committed_bar: CommittedBarEvent


class StrategyCycleDispatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StrategyCycleDispatchOutcome:
    """Orchestration-level outcome for one attempted strategy cycle."""

    strategy_instance_id: str
    status: StrategyCycleDispatchStatus
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.strategy_instance_id.strip():
            raise ValueError("strategy_instance_id must be a non-empty string")
        if self.status is StrategyCycleDispatchStatus.SUCCEEDED:
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("successful outcome cannot contain error details")
        elif self.error_code is None:
            raise ValueError("failed outcome requires error_code")

    @classmethod
    def succeeded(cls, strategy_instance_id: str) -> "StrategyCycleDispatchOutcome":
        return cls(
            strategy_instance_id=strategy_instance_id,
            status=StrategyCycleDispatchStatus.SUCCEEDED,
        )

    @classmethod
    def failed(
        cls,
        strategy_instance_id: str,
        *,
        error_code: str,
        error_message: str | None = None,
    ) -> "StrategyCycleDispatchOutcome":
        return cls(
            strategy_instance_id=strategy_instance_id,
            status=StrategyCycleDispatchStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )


@dataclass(frozen=True, slots=True)
class CommittedBarOrchestrationResult:
    """Aggregate technical result for fan-out of one committed bar."""

    selected_count: int
    attempted_count: int
    succeeded_count: int
    failed_count: int
    outcomes: tuple[StrategyCycleDispatchOutcome, ...]

    def __post_init__(self) -> None:
        counts = (
            self.selected_count,
            self.attempted_count,
            self.succeeded_count,
            self.failed_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("orchestration counts must be non-negative")
        if self.attempted_count != len(self.outcomes):
            raise ValueError("attempted_count must equal the number of outcomes")
        if self.succeeded_count + self.failed_count != self.attempted_count:
            raise ValueError("success and failure counts must equal attempted_count")
        if self.attempted_count != self.selected_count:
            raise ValueError("every selected deployment must be attempted exactly once")
