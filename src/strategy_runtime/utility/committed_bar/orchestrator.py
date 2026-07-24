"""Thin application coordinator for one accepted committed-bar event."""

from collections.abc import Callable
from typing import TypeVar

from strategy_runtime.utility.committed_bar.errors import (
    CommittedBarPreparationError,
    UpstreamOrchestrationStage,
)
from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    CommittedBarOrchestrationResult,
    StrategyBarProcessingUnit,
    StrategyCycleDispatchOutcome,
    StrategyCycleDispatchStatus,
)
from strategy_runtime.utility.committed_bar.ports import (
    DeploymentCatalogPort,
    DeploymentSelectorPort,
    ProcessingJournalPort,
    StrategyCycleDispatchPort,
)

ResultT = TypeVar("ResultT")


class CommittedBarOrchestrator[SnapshotT, DeploymentT]:
    """Coordinate autonomous ports and fan out one bar to strategy cycles."""

    def __init__(
        self,
        *,
        deployment_catalog: DeploymentCatalogPort[SnapshotT],
        deployment_selector: DeploymentSelectorPort[SnapshotT, DeploymentT],
        strategy_cycle_dispatcher: StrategyCycleDispatchPort[DeploymentT],
        processing_journal: ProcessingJournalPort,
    ) -> None:
        self._deployment_catalog = deployment_catalog
        self._deployment_selector = deployment_selector
        self._strategy_cycle_dispatcher = strategy_cycle_dispatcher
        self._processing_journal = processing_journal

    def process(
        self,
        committed_bar: CommittedBarEvent,
    ) -> CommittedBarOrchestrationResult:
        self._processing_journal.orchestration_started(
            event=committed_bar,
        )

        snapshot = self._prepare(
            stage=UpstreamOrchestrationStage.DEPLOYMENT_CATALOG,
            committed_bar=committed_bar,
            operation=self._deployment_catalog.load_snapshot,
        )
        selected = self._prepare(
            stage=UpstreamOrchestrationStage.DEPLOYMENT_SELECTION,
            committed_bar=committed_bar,
            operation=lambda: self._deployment_selector.select(
                event=committed_bar,
                snapshot=snapshot,
            ),
        )

        outcomes: list[StrategyCycleDispatchOutcome] = []
        for selected_deployment in sorted(
            selected,
            key=lambda item: item.strategy_instance_id,
        ):
            unit = StrategyBarProcessingUnit(
                strategy_instance_id=selected_deployment.strategy_instance_id,
                deployment=selected_deployment.deployment,
                committed_bar=committed_bar,
            )
            try:
                outcome = self._strategy_cycle_dispatcher.dispatch(unit)
            except Exception as error:
                outcome = StrategyCycleDispatchOutcome.failed(
                    selected_deployment.strategy_instance_id,
                    error_code="strategy_cycle_dispatch_failed",
                    error_message=str(error) or error.__class__.__name__,
                )
            else:
                if outcome.strategy_instance_id != selected_deployment.strategy_instance_id:
                    outcome = StrategyCycleDispatchOutcome.failed(
                        selected_deployment.strategy_instance_id,
                        error_code="strategy_cycle_outcome_identity_mismatch",
                        error_message=(
                            "dispatcher returned an outcome for a different deployment identity"
                        ),
                    )
            outcomes.append(outcome)
            self._processing_journal.strategy_cycle_outcome(
                event=committed_bar,
                outcome=outcome,
            )

        result = self._build_result(outcomes)
        self._processing_journal.orchestration_completed(
            event=committed_bar,
            result=result,
        )
        return result

    def _prepare(
        self,
        *,
        stage: UpstreamOrchestrationStage,
        committed_bar: CommittedBarEvent,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        try:
            return operation()
        except Exception as error:
            self._processing_journal.orchestration_failed(
                event=committed_bar,
                stage=stage.value,
                error=error,
            )
            raise CommittedBarPreparationError(
                stage=stage,
                cause=error,
            ) from error

    @staticmethod
    def _build_result(
        outcomes: list[StrategyCycleDispatchOutcome],
    ) -> CommittedBarOrchestrationResult:
        succeeded_count = sum(
            outcome.status is StrategyCycleDispatchStatus.SUCCEEDED for outcome in outcomes
        )
        failed_count = len(outcomes) - succeeded_count
        frozen_outcomes = tuple(outcomes)
        return CommittedBarOrchestrationResult(
            selected_count=len(frozen_outcomes),
            attempted_count=len(frozen_outcomes),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            outcomes=frozen_outcomes,
        )
