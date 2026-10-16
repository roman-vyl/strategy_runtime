## Why

Strategy Runtime reads its deployment specifications from a flat directory on every closed bar,
but nothing outside the process can ask which strategy instances are registered. A Runtime
Dashboard needs that list first. Everything the list needs already exists in the deployment
catalog snapshot, so the first step only exposes it.

## What Changes

- New read-only endpoint `GET /v1/strategy-instances`. Each request reads the deployment
  catalog once and returns the accepted deployments (enabled and disabled), plus the catalog's
  own diagnostics: `invalid_files` and `duplicate_identities`.
- Per strategy instance: `strategy_instance_id`, `strategy_id`, `instrument`,
  `base_timeframe`, `enabled`, `source_path`. `enabled` is the value from the spec file.
- Wiring only: a response model set in `adapters/http/models.py`, one route in
  `adapters/http/app.py` that receives a callable, and the callable built in
  `bootstrap/application.py` over the existing `FilesystemDeploymentCatalog.load_snapshot`.

## Out of Scope

`raw_spec`; Runtime state (trade cycles, recovery markers, risk multiplier, the orphaned
`loadtest-*` cycles); any new storage or cache; changing the meaning or source of `enabled`;
enabling, disabling or any other management; Engine, ABI, Journal, frontend; pagination and
filtering. The known defect where a spec containing `1e999` makes `load_snapshot()` raise
(and breaks bar processing) is tracked as its own issue and is not fixed here.

## Capabilities

### New Capabilities

- `strategy-instance-list`: read-only HTTP listing of the registered strategy instances and
  the catalog diagnostics.

## Impact

- `src/strategy_runtime/adapters/http/models.py`, `adapters/http/app.py`,
  `bootstrap/application.py`.
- No change to trading logic, orchestration, the state repository, the catalog or the processing
  journal. The architecture rule that `app.py` imports no infrastructure, repository or mutex
  stays intact.
