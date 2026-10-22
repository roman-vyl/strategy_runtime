# strategy-instance-list Specification

## Purpose
Define the read-only HTTP listing of the strategy instances registered in the deployment
catalog, together with the catalog's invalid-file and duplicate-identity diagnostics, and its
failure responses.
## Requirements
### Requirement: Runtime lists registered strategy instances over HTTP

Strategy Runtime SHALL expose `GET /v1/strategy-instances`, which reads the deployment catalog
and returns every accepted strategy deployment, enabled or disabled, together with the
catalog's invalid-file and duplicate-identity diagnostics.

#### Scenario: Return enabled and disabled instances
- **WHEN** the catalog contains accepted deployments with `enabled` true and false
- **AND** Runtime is ready
- **THEN** Runtime returns `200 OK`
- **AND** `strategy_instances` contains every accepted deployment in catalog order (by file name)
- **AND** each item has exactly `strategy_instance_id`, `strategy_id`, `instrument`, `base_timeframe`, `enabled` and `source_path`
- **AND** `enabled` is the value in the deployment file

#### Scenario: Response excludes specification and state
- **WHEN** Runtime returns the list
- **THEN** no item contains `raw_spec`, trade-cycle, recovery-marker, risk-multiplier or any other Runtime state field

#### Scenario: Empty catalog
- **WHEN** the catalog directory contains no spec files
- **THEN** Runtime returns `200 OK` with `scanned_file_count` 0 and empty `strategy_instances`, `invalid_files` and `duplicate_identities`

### Requirement: The list carries the catalog diagnostics unchanged

The response SHALL include `scanned_file_count`, `invalid_files` and `duplicate_identities`
using the catalog snapshot's own structure, so an absent strategy can be explained.

#### Scenario: Invalid file is reported
- **WHEN** a spec file cannot be accepted
- **THEN** `invalid_files` contains an item with that file's `source_path`, the catalog's `error_code` and `error_message` (or `null`)
- **AND** the file is not in `strategy_instances`

#### Scenario: Duplicate identity is reported
- **WHEN** two spec files derive the same `strategy_instance_id`
- **THEN** `duplicate_identities` contains one item with that `strategy_instance_id` and the sorted `source_paths` of both files
- **AND** neither file's deployment is in `strategy_instances`

### Requirement: Reading the list is read-only and reads the catalog per request

Each request SHALL read the deployment catalog once and SHALL NOT change any state.

#### Scenario: Catalog changes between requests
- **WHEN** a spec file is added, changed or removed between two requests
- **THEN** the second response reflects the directory as it is at that request

#### Scenario: No side effects
- **WHEN** a list request is served
- **THEN** Runtime does not write the state store, the processing journal or the catalog, and does not touch the intake queue or any per-instance mutex

#### Scenario: Other methods are not allowed
- **WHEN** a client sends `POST`, `PUT`, `PATCH` or `DELETE` to `/v1/strategy-instances`
- **THEN** Runtime returns `405 Method Not Allowed`

### Requirement: The list reports failures explicitly

Strategy Runtime SHALL answer a list request that cannot be served with a distinct status for each failure kind and SHALL NOT return a partial list.

#### Scenario: Runtime is not ready
- **WHEN** the process is live but startup readiness is false, or the list provider is not wired
- **THEN** Runtime returns `503 {"status":"not_ready"}`

#### Scenario: Catalog directory cannot be read
- **WHEN** the catalog directory scan fails
- **THEN** Runtime returns `503 {"status":"catalog_unavailable"}`

#### Scenario: Unexpected failure
- **WHEN** reading the catalog raises any other exception
- **THEN** Runtime returns `500 {"status":"internal_error"}` and logs the exception

