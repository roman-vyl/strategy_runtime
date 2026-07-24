# Runtime deployment-local activation decision — 2026-07-23

## Decision

Remove the standalone activation module and persisted `strategy_activation.json`. Every Runtime deployment JSON now requires `enabled: bool`.

## Identity boundary

`enabled` is operational metadata and is excluded from derived `strategy_instance_id`. Therefore toggling activation preserves identity, while changes to strategy semantics, ticker, or base timeframe create a new identity.

## Runtime flow

`FilesystemDeploymentCatalog -> CommittedBarDeploymentSelector -> CommittedBarOrchestrator`. The selector directly filters `deployment.enabled` plus exact ticker/timeframe equality.

## Removed surface

- `utility.activation`
- `JsonFileActivationResolver`
- `ActivationResolution` and new-deployment activation policy
- `RUNTIME_ACTIVATION_PATH`
- activation state reconciliation, orphan IDs, activation read/write failures
- activation preparation stage in committed-bar orchestration
