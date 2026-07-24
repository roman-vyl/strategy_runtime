## Context

`CommittedBarOrchestrator` needs one current immutable catalog snapshot for every accepted committed bar. The catalog answers which valid Runtime deployment documents currently exist and which candidates or identities were rejected. It does not decide which deployment applies to a particular bar.

## Goals / Non-Goals

**Goals:**

- Implement the orchestrator-owned `DeploymentCatalogPort` directly.
- Discover direct visible lowercase JSON files from one configured flat directory.
- Parse and validate candidates independently.
- Return deeply immutable accepted deployments and immutable diagnostics.
- Derive stable identity from strategy semantics and market coordinates.
- Fail closed on duplicate identities.
- Preserve the required deployment-local `enabled` value without deriving activation state.

**Non-Goals:**

- No committed-bar matching or selection.
- No external activation store, reconciliation, or lifecycle.
- No strategy-cycle dispatch, Engine, ABI, HTTP, or trading behavior.
- No recursive directory scan.
- No compatibility adapter around a superseded registry.

## Decisions

### Keep the capability in one autonomous utility package

The implemented package is:

```text
src/strategy_runtime/utility/deployment_catalog/
├── __init__.py
├── errors.py
├── filesystem_adapter.py
├── identity.py
└── models.py
```

It directly satisfies:

```text
DeploymentCatalogPort.load_snapshot()
    -> DeploymentCatalogSnapshot
```

### Discover candidates deterministically

`FilesystemDeploymentCatalog` scans one flat configured directory. Only direct, visible files whose suffix is exactly `.json` are candidates. Candidate filenames are sorted before parsing.

An unavailable catalog root is a catalog-level `DeploymentCatalogUnavailableError`. A failure confined to one candidate becomes `InvalidDeploymentFile` and does not reject unrelated valid candidates.

### Derive identity from semantic deployment content

Every accepted document contains:

```text
enabled: bool
ticker: non-empty string
base_timeframe: non-empty string
strategy_id: non-empty string
raw_spec: JSON object
```

The catalog derives:

```text
strategy_instance_id =
    strategy_id + ":" + sha256(
        canonical_json(strategy_id, ticker, base_timeframe, raw_spec)
    )[:24]
```

Filename, formatting, key order, `enabled`, and unknown additive top-level metadata do not affect identity. `strategy_instance_id`, `strategy_version`, and `compatibility_profile` are forbidden input fields.

### Return immutable models and explicit diagnostics

`DeploymentSpecification` contains:

```text
strategy_instance_id
enabled
instrument
base_timeframe
strategy_id
raw_spec
source_path
```

`raw_spec` is detached and recursively frozen. `DeploymentCatalogSnapshot` contains:

```text
scanned_file_count
accepted_deployments
invalid_files
duplicate_identities
```

It provides exact lookup by `strategy_instance_id` and no stream-selection method.

### Exclude every duplicate identity

Candidates are grouped by derived `strategy_instance_id`. If a group contains more than one file, every member is excluded and one sorted `DuplicateDeploymentIdentity` diagnostic records the identity and source paths.

## Risks / Trade-offs

- [Truncated identity digest has a theoretical collision risk] → Duplicate identities fail closed and the digest length is fixed by the current internal contract.
- [Unknown top-level fields are ignored] → Identity and behavior depend only on the documented Runtime deployment envelope.
- [One flat directory limits organization] → Recursive discovery is deliberately excluded to keep candidate ownership unambiguous.

## Migration Plan

1. Replace the superseded webhook-coupled registry with the autonomous utility package.
2. Wire the catalog directly into `CommittedBarOrchestrator`.
3. Keep deployment selection in its own capability.
4. Validate catalog behavior, architecture boundaries, and the complete Runtime suite.
