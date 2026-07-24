## Context

`CommittedBarOrchestrator` receives one catalog snapshot and one committed-bar event. It needs a pure selector that identifies exactly which accepted deployment specifications apply to that bar.

## Goals / Non-Goals

**Goals:**

- Filter accepted deployments by the required deployment-local `enabled` flag.
- Require exact, case-sensitive instrument and base-timeframe equality.
- Return immutable orchestrator-owned `SelectedDeployment` values.
- Remain deterministic and free of I/O.

**Non-Goals:**

- No activation snapshot, persistence, reconciliation, or orphan handling.
- No catalog discovery or duplicate handling.
- No dispatch ordering.
- No Runtime position, Engine, ABI, journal, or trading behavior.

## Decisions

### Consume only the committed bar and catalog snapshot

The selector implements:

```text
DeploymentSelectorPort.select(event, snapshot)
    -> tuple[SelectedDeployment, ...]
```

There is no separate activation input. The catalog validates and preserves the required `enabled: bool`; the selector consumes that value directly.

### Use exact market-coordinate equality

A deployment is selected only when:

```text
deployment.enabled is true
and deployment.instrument == event.instrument
and deployment.base_timeframe == event.timeframe
```

No normalization or case folding occurs. Catalog order is preserved by the selector; final stable-identity ordering belongs to `CommittedBarOrchestrator`.

## Risks / Trade-offs

- [Equivalent market aliases do not match] → Upstream configuration must use canonical exact coordinates.
- [Selector preserves catalog order] → The orchestrator owns deterministic dispatch sorting.
