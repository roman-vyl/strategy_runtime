"""Deployment-catalog failures."""


class DeploymentCatalogUnavailableError(RuntimeError):
    """Raised when the configured deployment catalog cannot be scanned."""
