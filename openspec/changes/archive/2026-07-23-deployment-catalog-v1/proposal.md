## Why

`CommittedBarOrchestrator` requires one current immutable catalog snapshot for every accepted committed bar. Deployment discovery must be an autonomous capability with a narrow contract and no activation, committed-bar selection, Engine, ABI, or trading responsibilities.

## What Changes

- Add a `FilesystemDeploymentCatalog` implementing `DeploymentCatalogPort` directly.
- Add immutable deployment-catalog domain models and typed failures.
- Discover deployment JSON files deterministically and validate candidates independently.
- Require Runtime deployment JSON to contain `enabled`, ticker, base timeframe, strategy identity, and an object-valued raw specification while forbidding obsolete identity fields.
- Derive `strategy_instance_id` from canonical strategy semantics plus ticker and base timeframe.
- Deep-freeze accepted deployment specifications.
- Detect duplicate derived deployment identities and exclude every member of a duplicate group.
- Preserve the deployment-local `enabled` value without performing committed-bar selection.
- Return discovery diagnostics without deriving a separate activation result.
- Add isolated domain, infrastructure, and architecture tests.

## Capabilities

### New Capabilities

- `deployment-catalog`: Discovers, validates, identifies, and freezes deployment documents from one configured filesystem directory.

### Modified Capabilities

None.

## Impact

- Provides the catalog capability required by `CommittedBarOrchestrator`.
- Establishes the canonical deployment discovery models and API.
- Keeps committed-bar deployment selection as a separate capability.
