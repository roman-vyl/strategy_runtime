## Why

After the closed-bar HTTP capability accepts a notification, Strategy Runtime needs one application-level coordinator that owns the utility processing sequence without absorbing deployment discovery, deployment selection, semantic Runtime, Engine, ABI, or trading behavior.

## What Changes

- Add `CommittedBarOrchestrator` as the application boundary for one accepted committed-bar event.
- Depend on typed ports for deployment discovery, deployment selection, strategy-cycle dispatch, and processing journaling.
- Create one immutable `StrategyBarProcessingUnit` per selected deployment.
- Dispatch selected deployments in deterministic stable-identity order.
- Isolate one dispatch failure from remaining selected units.
- Reject dispatcher outcomes whose `strategy_instance_id` does not match the attempted unit.
- Return a validated aggregate orchestration result.
- Add `StrategyCycleHandoffBoundary` as a terminal or sink-backed implementation of the dispatch port.
- Keep trace identity, semantic Runtime state, Engine, ABI, order, and exchange behavior outside the utility object graph.

## Capabilities

### New Capabilities

- `committed-bar-orchestrator`: Coordinates one committed bar across catalog, selector, journal, and strategy-cycle dispatch ports.
- `strategy-cycle-handoff`: Accepts one prepared processing unit at the terminal utility boundary and optionally forwards it to an attached downstream sink.

### Modified Capabilities

None.

## Impact

- Utility committed-bar orchestration models, ports, errors, and coordinator.
- Terminal strategy-cycle handoff boundary.
- Production composition root wiring.
- Unit and integration tests for sequencing, deterministic fan-out, failure isolation, outcome identity, and handoff behavior.
- No semantic Runtime, Strategy Engine, ABI, order, receipt, or exchange contract changes.
