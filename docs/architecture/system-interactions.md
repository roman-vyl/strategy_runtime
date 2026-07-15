# System Interactions

## Live runtime pipeline

```text
Bybit market data
        |
        v
Market Data Service
        |
        | ingest and canonical commit
        v
ready canonical stream
        |
        | after successful commit of a newly closed bar
        | HTTP webhook
        v
Strategy Runtime
        |
        | find active specs whose configured base stream matches the updated stream
        |
        | for each relevant active spec
        v
Strategy Engine
        |
        | calculate the current point using the spec and current canonical market data
        | calculate the current strategy point 0
        v
Strategy Runtime
        |
        | every successful current-point result
        v
ABI Executor
        |
        | reconcile as no-op / create / cancel / replace / update
        v
Bybit
```

## Webhook placement


### Every-bar handoff to ABI

For every permitted strategy instance triggered by its base-stream webhook, a successful Strategy Engine current-point result is forwarded to ABI Executor on every bar. Runtime does not suppress a result because it appears unchanged, neutral, or equivalent to the preceding bar.

ABI owns semantic reconciliation against its current orders and positions, including deciding whether the newly supplied result is a no-op, requires a pending-order replacement, requires cancellation, or requires an allowed protection update. The exact accepted input model and reconciliation behaviour must be verified and, where necessary, added in the ABI repository through Gate 02.

The Runtime does not decide whether the result changes exchange state.

The webhook is emitted by Market Data Service only after the newly closed candle has been successfully committed as canonical data.

```text
closed candle observed
        |
        v
canonical ingestion
        |
        v
successful commit
        |
        v
MDS sends webhook to Strategy Runtime
```

The webhook is a wake-up trigger for Strategy Runtime. Its bar identity describes which stream update caused the notification, but it is not forwarded to Strategy Engine as the calculation right edge. It does not transfer responsibility for candle storage, stream selection, timestamp alignment, or strategy calculation to Strategy Runtime.

## Current-point calculation semantics

```text
MDS webhook: base stream changed
        |
        v
Strategy Runtime: select active specs bound to ticker + timeframe
        |
        v
Strategy Engine: calculate current point 0
```

Runtime supplies the active strategy spec and its configured `ticker + timeframe`. It does not supply a historical range or a triggering-bar identity. Runtime also does not inspect the spec to discover additional stream dependencies.

The supplied `ticker + timeframe` is the only Runtime-visible base stream in v1. Strategy Engine remains responsible for its own calculation and market-data access.

## Evaluation trigger stream

Each active runtime strategy has one base evaluation stream. Only a webhook for that base stream triggers a Strategy Engine calculation for the strategy.

Other streams that Strategy Engine may use internally do not participate in Runtime v1 routing. Their webhooks do not trigger this strategy because Runtime knows only the configured base stream.

```text
base stream webhook
        |
        v
Strategy Runtime selects the active strategy
        |
        v
Strategy Engine reads latest data from all required ready streams
        |
        v
calculate current point 0

context stream webhook
        |
        v
no calculation trigger for that strategy
```

This rule avoids duplicate evaluations when base and higher-timeframe candles close on the same wall-clock boundary.

## Known non-base readiness gap

Runtime v1 does not know which non-base streams may be used internally by Strategy Engine. Therefore, if such a stream leaves `ready`, Runtime does not automatically suspend the strategy and does not request ABI cancellation for it.

```text
non-base stream -> non-ready
        |
        v
MDS may report the transition
        |
        v
Runtime has no v1 binding from that stream to the strategy
        |
        v
no automatic reaction for that strategy
```

This limitation is accepted for v1 and must be revisited before full multi-stream safety coverage is claimed.

## Known timing risk

The current design assumes that when a base-timeframe webhook is delivered, any higher-timeframe candle that closes on the same boundary is already available as latest canonical data in its own `ready` stream.

A possible asynchronous timing failure remains:

```text
5m candle committed and webhook sent
        |
        v
Strategy Engine starts calculation
        |
        +--> latest 5m candle is new
        |
        +--> latest 1h candle is still the previous one
```

No automatic waiting, cross-stream barrier, or additional validation is approved at this stage. This is recorded as a future integration risk that must be tested manually with real multi-timeframe stream timing before production use.

## Backtest separation

```text
Research Service
        |
        v
Strategy Engine
        |
        v
Research Service
```

Strategy Runtime does not participate in this path.

## Stream loses readiness

The live safety path is stream-scoped, not service-global.

```text
MDS stream: ready -> non-ready
        |
        | stream-state transition notification
        v
Strategy Runtime
        |
        | find active strategy instances whose configured base stream matches this stream
        |
        +--> suspend affected instances only
        |
        +--> no new Engine evaluation or entry intent for those instances
        |
        +--> request ABI scoped cancellation of pending non-position orders
                        |
                        +--> preserve open positions
                        +--> preserve stop-loss / take-profit protection
```

Independent base streams and their strategy instances continue operating. Strategies that only depend on the affected stream internally, without using it as their configured base stream, are not detected in v1.

The exact contracts and recovery behaviour are subject to mandatory cross-repository gates documented in `implementation-gates.md`.

## Strategy activation and deactivation

### Deactivation

```text
Runtime frontend / control path
        |
        | is_active: true -> false
        v
Strategy Runtime
        |
        +--> remove strategy from base-stream routing
        +--> stop future Strategy Engine calculations
        +--> request ABI cancellation of pending entry orders
                        |
                        +--> preserve open positions
                        +--> preserve position-linked protection
```

A strategy that has been deactivated must not open a new position through an entry order that was still pending at the time of deactivation.

### Reactivation in v1

```text
is_active: false -> true
        |
        v
strategy becomes eligible for routing
        |
        v
wait for next base-stream webhook
        |
        v
normal Strategy Engine current-point calculation
```

V1 intentionally does not perform an immediate calculation when a strategy is reactivated. This avoids adding a second calculation-trigger mechanism before its live-trading semantics are designed.

An immediate out-of-band calculation may be a useful future operator feature, but it remains outside the approved v1 behaviour.

## File discovery and activation reconciliation

Runtime v1 does not require a database or filesystem watcher for strategy onboarding.

```text
operator places a new spec file in the configured directory
        |
        | no immediate Runtime action
        v
next MDS webhook arrives
        |
        v
Runtime scans/reconciles the spec directory with activation-registry JSON
        |
        +--> known strategy: use persisted is_active
        |
        +--> new strategy: persist is_active=true by default
        |
        v
if active and ticker + timeframe matches the webhook
        |
        v
send the spec to Strategy Engine
```

An explicit HTTPS API update changes the persisted activation override. The override survives Runtime restart and has priority over the default-on-first-discovery behaviour.

The spec directory and activation JSON are separate on purpose: file presence represents existence, while `is_active` represents live-execution permission.


## File removal and future managed deletion

```text
operator removes a spec file manually
        |
        | no filesystem watcher in v1
        v
Runtime continues with its current in-memory view
        |
        v
next ordinary MDS webhook
        |
        v
spec-directory reconciliation notices the file is absent
```

Therefore, manual file removal is not an immediate stop mechanism in v1. Before the HTTPS `is_active` control path is available, there is no supported managed delete operation that can first stop routing and then remove the strategy definition.

The intended future frontend/API sequence is:

```text
Stop strategy
    -> persist is_active=false
    -> stop Engine routing
    -> cancel pending entry orders in ABI

Delete strategy
    -> remove it from the Runtime registry
    -> delete the spec file
```

Open positions and their protective orders remain outside the delete operation, consistent with the agreed deactivation boundary.


## Validation boundary for the initial smoke-test stage

Runtime performs no standalone semantic validation of discovered specs in v1.

```text
Workbench/frontend or CLI authoring path
        |
        | construct and validate spec
        v
operator places the resulting file in Runtime spec directory
        |
        v
Runtime discovers and routes it without reimplementing the validator
        |
        v
Strategy Engine attempts current-point evaluation
```

This is an accepted smoke-test-stage limitation. A structurally unreadable file or an Engine-incompatible spec may fail processing. Runtime must surface the failure, but it does not claim that every discovered file is semantically valid.


## Cold-start trigger behaviour

Runtime startup restores its local configuration and exposes the API, but does not initiate an evaluation. It reads the spec directory and persisted activation registry, opens the journal sink, and waits. The first live calculation after startup occurs only when a new MDS closed-bar webhook reaches the Runtime endpoint. No startup replay or self-triggered current-point evaluation exists in v1.
