## MODIFIED Requirements

### Requirement: Runtime lists registered strategy instances over HTTP

Strategy Runtime SHALL expose `GET /v1/strategy-instances`, which reads the deployment catalog
and returns every accepted strategy deployment, enabled or disabled (by the stored value), together with the
catalog's invalid-file and duplicate-identity diagnostics.

#### Scenario: Return enabled and disabled instances
- **WHEN** the catalog contains accepted deployments with `enabled` true and false
- **AND** Runtime is ready
- **THEN** Runtime returns `200 OK`
- **AND** `strategy_instances` contains every accepted deployment in catalog order (by file name)
- **AND** each item has exactly `strategy_instance_id`, `strategy_id`, `instrument`, `base_timeframe`, `enabled` and `source_path`
- **AND** `enabled` is Runtime's stored value, or the value in the spec file for an instance Runtime has not yet recorded

#### Scenario: Response excludes specification and state
- **WHEN** Runtime returns the list
- **THEN** no item contains `raw_spec`, trade-cycle, recovery-marker, risk-multiplier or any other Runtime state field

#### Scenario: Empty catalog
- **WHEN** the catalog directory contains no spec files
- **THEN** Runtime returns `200 OK` with `scanned_file_count` 0 and empty `strategy_instances`, `invalid_files` and `duplicate_identities`
