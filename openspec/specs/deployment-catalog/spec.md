# deployment-catalog Specification

## Purpose
Define deterministic filesystem discovery, validation, immutable modeling, derived identity, and fail-closed duplicate handling for Runtime deployment documents.

## Requirements
### Requirement: Immutable deployment catalog snapshot

The Runtime MUST expose a deployment-catalog capability that returns one immutable snapshot of currently discovered deployment specifications.

#### Scenario: Valid deployments are discovered

- **WHEN** `FilesystemDeploymentCatalog.load_snapshot()` scans a configured catalog directory containing valid deployment JSON files
- **THEN** it returns those deployments in `DeploymentCatalogSnapshot.accepted_deployments`
- **AND** every accepted deployment and its nested raw specification are immutable

#### Scenario: Empty catalog is valid

- **WHEN** the configured catalog contains no candidate deployment files
- **THEN** the catalog returns a successful empty snapshot

### Requirement: Deterministic flat candidate discovery

The filesystem catalog SHALL scan only direct, visible files with the lowercase `.json` suffix and SHALL enumerate them by filename.

#### Scenario: Ignore non-candidate paths

- **WHEN** the catalog directory contains hidden JSON files, nested JSON files, non-JSON files, and direct visible lowercase JSON files
- **THEN** only direct visible lowercase JSON files contribute to `scanned_file_count`
- **AND** candidates are processed in deterministic filename order

### Requirement: Independent file validation

One invalid candidate file MUST NOT prevent unrelated valid deployment files from appearing in the snapshot.

#### Scenario: One invalid file exists beside one valid file

- **WHEN** one candidate cannot be parsed or lacks required deployment fields
- **THEN** that file appears in `invalid_files`
- **AND** the valid deployment remains accepted

#### Scenario: Non-finite JSON number is rejected independently

- **WHEN** one candidate contains a non-finite numeric literal such as `NaN` or `Infinity`
- **THEN** that file appears in `invalid_files`
- **AND** unrelated valid deployments remain accepted

### Requirement: Derived immutable deployment identity

Runtime deployment JSON MUST contain `enabled`, `ticker`, `base_timeframe`, `strategy_id`, and `raw_spec`, and MUST NOT contain manually assigned or obsolete identity fields. The catalog MUST derive `strategy_instance_id` deterministically from `strategy_id`, `ticker`, `base_timeframe`, and `raw_spec`.

#### Scenario: Semantic or market input changes

- **WHEN** any identity-basis field changes
- **THEN** the derived `strategy_instance_id` changes

#### Scenario: Formatting or source path changes

- **WHEN** semantic content is unchanged but filename, formatting, or JSON key order changes
- **THEN** the derived `strategy_instance_id` remains unchanged

#### Scenario: Manual identity is supplied

- **WHEN** an input JSON contains `strategy_instance_id`
- **THEN** the file is rejected as containing a forbidden derived field

#### Scenario: Obsolete identity metadata is supplied

- **WHEN** an input JSON contains `strategy_version` or `compatibility_profile`
- **THEN** the file is rejected as containing a forbidden obsolete field

#### Scenario: Additive non-semantic metadata changes

- **WHEN** fields outside `strategy_id`, `ticker`, `base_timeframe`, and `raw_spec` change
- **THEN** the derived `strategy_instance_id` remains unchanged

### Requirement: Duplicate identities fail closed

All deployment files resolving to one derived deployment identity MUST be excluded from accepted deployments.

#### Scenario: Duplicate stable deployment identity

- **WHEN** two or more files resolve to the same derived stable deployment identity
- **THEN** none of those files is accepted
- **AND** one duplicate diagnostic identifies the stable identity and participating source paths

### Requirement: Catalog scope excludes selection and activation

The deployment catalog MUST preserve the validated deployment-local `enabled` value but MUST NOT decide whether a deployment is applicable to a committed bar or derive a separate activation result.

#### Scenario: Snapshot is consumed downstream

- **WHEN** the catalog returns a snapshot
- **THEN** the snapshot contains discovery results and diagnostics only
- **AND** it exposes no committed-bar stream-selection behavior
- **AND** it preserves `enabled` as input data rather than a selection result

### Requirement: Direct orchestrator port conformance

The filesystem catalog MUST implement the orchestrator-owned `DeploymentCatalogPort` directly.

#### Scenario: Orchestrator requests a snapshot

- **WHEN** `CommittedBarOrchestrator` invokes `load_snapshot()`
- **THEN** no compatibility adapter or superseded registry object is required

### Requirement: Deployment-local activation flag

Every Runtime deployment document SHALL contain a required boolean `enabled` field.

#### Scenario: Enabled deployment is accepted
- **WHEN** `enabled` is a JSON boolean
- **THEN** the accepted `DeploymentSpecification` SHALL preserve that value

#### Scenario: Missing or invalid enabled field
- **WHEN** `enabled` is absent or is not a JSON boolean
- **THEN** the file SHALL be classified invalid and excluded fail-closed

### Requirement: Activation does not change deployment identity

`enabled` SHALL NOT participate in `strategy_instance_id` derivation.

#### Scenario: Only enabled changes
- **GIVEN** two documents whose semantic deployment payloads are identical
- **AND** their only difference is `enabled`
- **THEN** they SHALL derive the same `strategy_instance_id`

### Requirement: Catalog-root failure is explicit

The filesystem catalog SHALL raise a catalog-level typed failure when its configured root cannot be enumerated.

#### Scenario: Catalog root is unavailable

- **WHEN** the configured catalog root is missing, unreadable, or not a directory
- **THEN** `load_snapshot()` raises `DeploymentCatalogUnavailableError`
- **AND** does not return a partial snapshot
