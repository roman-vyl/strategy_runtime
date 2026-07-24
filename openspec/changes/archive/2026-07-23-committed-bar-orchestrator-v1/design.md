## Context

The HTTP adapter schedules one validated `CommittedBarEvent` as in-process background work. The utility contour must discover the current deployments, select those applicable to the bar, and emit one independent processing unit per selection. Semantic Runtime behavior begins only after this handoff.

## Goals / Non-Goals

**Goals:**

- Own one stable top-level sequence per committed bar.
- Keep delegated behavior behind consumer-owned typed ports.
- Pass immutable models through the utility contour.
- Dispatch every selected deployment exactly once in deterministic order.
- Isolate per-unit failures and validate returned outcome identity.
- Record semantic lifecycle calls through a best-effort processing-journal implementation.
- Provide an explicit terminal boundary when no semantic Runtime sink is attached.

**Non-Goals:**

- No trace or processing-context propagation.
- No deployment parsing, identity derivation, or selection rules inside the orchestrator.
- No Runtime state, position interpretation, Engine route, projection, ABI, order, or exchange behavior.
- No durable queue, replay, retry, deduplication, or concurrent fan-out.

## Decisions

### Coordinate exactly four consumer-owned ports

The orchestrator depends on:

```text
DeploymentCatalogPort.load_snapshot()
DeploymentSelectorPort.select(event, snapshot)
StrategyCycleDispatchPort.dispatch(unit)
ProcessingJournalPort semantic lifecycle methods
```

There is no activation port. Activation is represented only by the deployment-local `enabled` field consumed by the selector.

### Keep the sequence directional and sequential

For one call to `process(committed_bar)`:

```text
1. journal.orchestration_started(event)
2. snapshot = catalog.load_snapshot()
3. selected = selector.select(event, snapshot)
4. sort selected by strategy_instance_id
5. for each selection:
   5.1 build StrategyBarProcessingUnit
   5.2 dispatch(unit)
   5.3 normalize exception or identity mismatch into a failed outcome
   5.4 journal.strategy_cycle_outcome(event, outcome)
6. build CommittedBarOrchestrationResult
7. journal.orchestration_completed(event, result)
8. return result
```

Catalog or selection failure is journaled and wrapped in `CommittedBarPreparationError`; no unit is dispatched.

### Pass only established immutable data

The models are:

```text
CommittedBarEvent
- instrument
- timeframe
- open_time_ms

StrategyBarProcessingUnit
- strategy_instance_id
- deployment
- committed_bar

StrategyCycleDispatchOutcome
- strategy_instance_id
- status
- error_code?
- error_message?

CommittedBarOrchestrationResult
- selected_count
- attempted_count
- succeeded_count
- failed_count
- outcomes
```

No trace ID, processing context, inferred position state, Engine projection, ABI state, order, or receipt enters these models.

### Fail closed on outcome identity mismatch

A dispatcher may return a typed success or failure. If its `strategy_instance_id` differs from the attempted selection, the orchestrator substitutes a failure for the attempted identity with error code `strategy_cycle_outcome_identity_mismatch`.

An exception raised by dispatch becomes `strategy_cycle_dispatch_failed`. Both failures remain isolated to that unit.

### Provide a minimal handoff boundary

`StrategyCycleHandoffBoundary` implements `StrategyCycleDispatchPort`.

- Without a sink, it is an explicit terminal acceptance point and returns success.
- With a sink, it passes the exact immutable unit to that callable and returns success.
- A sink exception crosses the boundary so `CommittedBarOrchestrator` can normalize and isolate it.

## Risks / Trade-offs

- [Sequential fan-out limits throughput] → Determinism and simple failure isolation are preferred for the first utility contour.
- [No sink reports terminal success] → This explicitly means utility handoff succeeded, not semantic calculation or trading success.
- [Journal calls are part of the sequence] → The production `JsonlProcessingJournal` satisfies its port by absorbing internal failures.

## Migration Plan

1. Introduce the autonomous `utility/committed_bar` package.
2. Implement catalog, selector, journal, and handoff ports separately.
3. Wire the concrete utility contour in the composition root.
4. Verify unit, architecture, and full production-composition behavior.
