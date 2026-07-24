# Strategy Runtime

`strategy_runtime` provides the production-composed committed-bar utility
contour and an independently callable semantic core through Strategy Engine
projection.

## Current planning documents

The active high-level design is indexed in
[`docs/system-plans/README.md`](docs/system-plans/README.md). The current semantic
Runtime sequence is defined by the master plan, state/lifecycle plan, contract
map, and the active OpenSpec changes for the state repository, open-position
resolver, and use-case router.

## Production composition boundary

```text
MDS committed-bar webhook
→ Deployment Catalog
→ Deployment Selector
→ CommittedBarOrchestrator
→ StrategyCycleHandoffBoundary
```

The final boundary emits one immutable `StrategyBarProcessingUnit` for every deployment whose required `enabled` flag is `true` that exactly matches the committed bar's instrument and base timeframe.

The utility contour deliberately does not decide or execute:

- Strategy Engine routes or requests;
- ABI state interpretation;
- position lifecycle;
- trading commands or exchange operations.

A downstream sink can be attached to `StrategyCycleHandoffBoundary` without
changing the utility contour. The default production composition does not attach
the semantic core and therefore treats this boundary as its terminal acceptance
point.

## Implemented components

- FastAPI service bootstrap and health endpoints;
- committed-bar webhook ingress with background processing;
- immutable filesystem deployment catalog;
- deployment-local `enabled` control embedded in each Runtime deployment config;
- exact committed-bar deployment selection;
- deterministic per-deployment fan-out and failure isolation;
- best-effort append-only JSONL processing journal;
- terminal strategy-cycle handoff boundary.

## Local setup

```bash
make install-dev
make verify
make run
```

`make install-dev` creates a repository-local `.venv` with Python 3.12.
All other Make targets require that exact environment and never fall back to a
system `python` or `python3`.

Default configuration is documented in `config/runtime.env.example`.

## HTTP surface

```text
GET  /health/live
GET  /health/ready
POST /v1/webhooks/closed-bar
```

Example webhook:

```bash
curl -X POST http://127.0.0.1:8093/v1/webhooks/closed-bar \
  -H 'content-type: application/json' \
  -d '{"instrument":"BTCUSDT.P","timeframe":"5m","open_time_ms":1784106300000}'
```

The webhook acknowledges accepted work before background orchestration completes.

## Documentation

- [`docs/system-plans/README.md`](docs/system-plans/README.md) — current
  architecture index.
- [`docs/system-plans/runtime-master-plan.md`](docs/system-plans/runtime-master-plan.md)
  — Runtime boundaries, implemented stopping point, and open architecture gates.
- [`docs/system-plans/runtime-state-and-lifecycle-plan.md`](docs/system-plans/runtime-state-and-lifecycle-plan.md)
  — state ownership and lifecycle design.
- [`docs/system-plans/runtime-contract-map.md`](docs/system-plans/runtime-contract-map.md)
  — current module-to-module contracts.

## Implemented semantic core boundary

The implemented Runtime core now covers the complete forward semantic path from one utility-selected deployment/bar unit through Strategy Engine projection:

```text
StrategyBarProcessingUnit
→ StrategyInstanceRuntimeStateRepository.get_or_create
→ ABI open-position lookup
→ route by position_open
→ live-entry or open-trade Strategy Engine projection
→ validated typed projection result
```

This boundary stops before applying Engine results. The semantic core does not
mutate `StrategyInstanceRuntimeState`, persist entry or management recipes,
construct ABI execution commands, or call ABI execution endpoints. State
application and execution behavior are outside the implemented semantic core and
remain explicit architecture gates in the System Plans.

The semantic core and ports are implemented and tested. The production
composition contains no ABI or Strategy Engine HTTP adapters and no physical
SQLite state repository.
