"""Consumer-owned ports required by the committed-bar orchestrator."""

from typing import Protocol, TypeVar

from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    CommittedBarOrchestrationResult,
    SelectedDeployment,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
)

SnapshotT_co = TypeVar("SnapshotT_co", covariant=True)
SnapshotT_contra = TypeVar("SnapshotT_contra", contravariant=True)
DeploymentT_co = TypeVar("DeploymentT_co", covariant=True)
DeploymentT_contra = TypeVar("DeploymentT_contra", contravariant=True)


class DeploymentCatalogPort(Protocol[SnapshotT_co]):
    def load_snapshot(self) -> SnapshotT_co:
        """Return one current immutable deployment catalog result."""
        ...


class DeploymentSelectorPort(Protocol[SnapshotT_contra, DeploymentT_co]):
    def select(
        self,
        *,
        event: CommittedBarEvent,
        snapshot: SnapshotT_contra,
    ) -> tuple[SelectedDeployment[DeploymentT_co], ...]:
        """Return enabled deployments applicable to the committed bar."""
        ...


class StrategyCycleDispatchPort(Protocol[DeploymentT_contra]):
    def dispatch(
        self,
        unit: StrategyBarProcessingUnit[DeploymentT_contra],
    ) -> StrategyCycleDispatchOutcome:
        """Dispatch one strategy/bar unit to the next application capability."""
        ...


class ProcessingJournalPort(Protocol):
    def orchestration_started(self, *, event: CommittedBarEvent) -> None: ...
    def orchestration_failed(
        self, *, event: CommittedBarEvent, stage: str, error: Exception
    ) -> None: ...
    def strategy_cycle_outcome(
        self, *, event: CommittedBarEvent, outcome: StrategyCycleDispatchOutcome
    ) -> None: ...
    def orchestration_completed(
        self, *, event: CommittedBarEvent, result: CommittedBarOrchestrationResult
    ) -> None: ...
