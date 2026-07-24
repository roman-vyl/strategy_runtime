"""Pure committed-bar deployment selection."""

from strategy_runtime.utility.committed_bar.models import (
    CommittedBarEvent,
    SelectedDeployment,
)
from strategy_runtime.utility.deployment_catalog import (
    DeploymentCatalogSnapshot,
    DeploymentSpecification,
)


class CommittedBarDeploymentSelector:
    """Select enabled accepted deployments matching one committed-bar stream."""

    def select(
        self,
        *,
        event: CommittedBarEvent,
        snapshot: DeploymentCatalogSnapshot,
    ) -> tuple[SelectedDeployment[DeploymentSpecification], ...]:
        return tuple(
            SelectedDeployment(
                strategy_instance_id=deployment.strategy_instance_id,
                deployment=deployment,
            )
            for deployment in snapshot.accepted_deployments
            if deployment.enabled
            and deployment.instrument == event.instrument
            and deployment.base_timeframe == event.timeframe
        )
