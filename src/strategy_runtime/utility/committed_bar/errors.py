"""Typed failures raised before committed-bar fan-out can begin."""

from enum import StrEnum


class UpstreamOrchestrationStage(StrEnum):
    DEPLOYMENT_CATALOG = "deployment_catalog"
    DEPLOYMENT_SELECTION = "deployment_selection"


class CommittedBarPreparationError(RuntimeError):
    """Raised when an upstream orchestration dependency prevents fan-out."""

    def __init__(
        self,
        *,
        stage: UpstreamOrchestrationStage,
        cause: Exception,
    ) -> None:
        super().__init__(f"committed-bar preparation failed at {stage}: {cause}")
        self.stage = stage
        self.cause = cause
