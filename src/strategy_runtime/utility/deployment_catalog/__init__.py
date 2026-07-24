"""Deployment-catalog domain capability."""

from strategy_runtime.utility.deployment_catalog.errors import (
    DeploymentCatalogUnavailableError,
)
from strategy_runtime.utility.deployment_catalog.identity import (
    derive_strategy_instance_id,
)
from strategy_runtime.utility.deployment_catalog.models import (
    DeploymentCatalogSnapshot,
    DeploymentSpecification,
    DuplicateDeploymentIdentity,
    FrozenJsonValue,
    InvalidDeploymentFile,
    freeze_json,
)

from .filesystem_adapter import FilesystemDeploymentCatalog

__all__ = [
    "DeploymentCatalogSnapshot",
    "DeploymentCatalogUnavailableError",
    "DeploymentSpecification",
    "DuplicateDeploymentIdentity",
    "FilesystemDeploymentCatalog",
    "FrozenJsonValue",
    "InvalidDeploymentFile",
    "derive_strategy_instance_id",
    "freeze_json",
]
