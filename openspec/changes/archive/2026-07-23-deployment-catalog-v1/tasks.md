## 1. Domain models

- [x] 1.1 Add the `utility/deployment_catalog` package.
- [x] 1.2 Add immutable `DeploymentSpecification`.
- [x] 1.3 Add immutable invalid-file and duplicate-identity diagnostics.
- [x] 1.4 Add immutable `DeploymentCatalogSnapshot` with identity lookup only.
- [x] 1.5 Add recursive immutable JSON freezing without importing superseded registry code.

## 2. Filesystem implementation

- [x] 2.1 Add `FilesystemDeploymentCatalog`.
- [x] 2.2 Implement deterministic candidate-file enumeration.
- [x] 2.3 Implement independent JSON parsing and required-field validation.
- [x] 2.3a Require ticker and base timeframe in the Runtime deployment envelope.
- [x] 2.3b Reject manually supplied `strategy_instance_id`.
- [x] 2.3c Derive stable identity from canonical strategy semantics and market coordinates.
- [x] 2.4 Implement duplicate stable-identity detection and fail-closed exclusion.
- [x] 2.5 Implement typed catalog-root and filesystem failures.
- [x] 2.6 Implement `load_snapshot()` with the exact orchestrator port signature.

## 3. Boundary cleanup

- [x] 3.1 Ensure the new snapshot has no stream-selection method.
- [x] 3.2 Ensure the new catalog contains no activation behavior.
- [x] 3.3 Ensure no superseded registry model, port, or class is imported.
- [x] 3.4 Remove superseded deployment-registry domain, port, infrastructure, and tests.

## 4. Verification

- [x] 4.1 Test empty catalog behavior.
- [x] 4.2 Test valid deployment discovery.
- [x] 4.3 Test invalid JSON and missing required fields.
- [x] 4.4 Test deep immutability.
- [x] 4.5 Test deterministic enumeration.
- [x] 4.6 Test duplicate identity fail-closed behavior.
- [x] 4.7 Test catalog-wide filesystem failure.
- [x] 4.8 Add an effective architecture test forbidding activation, selector, Engine, ABI, FastAPI, and superseded registry imports.
- [x] 4.9 Run the full test suite and Python compilation checks.
- [x] 4.10 Run `ruff` and `mypy`.
- [x] 4.11 Validate the OpenSpec change strictly with the local OpenSpec CLI.
- [x] 4.12 Test and isolate non-finite JSON numeric literals.
