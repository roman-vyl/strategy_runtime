# Strategy Runtime

`strategy_runtime` is the live orchestration service of the new BBB architecture.

It does not calculate strategies, store market candles, run backtests, or communicate with the exchange directly. Its role is to coordinate active live strategy specs:

```text
Market Data Service
        |
        | closed canonical bar webhook
        v
Strategy Runtime
        |
        | active spec + configured ticker/timeframe
        v
Strategy Engine
        |
        | current-bar calculation result
        v
Strategy Runtime
        |
        | every successful current-point result
        v
ABI Executor
        | reconcile desired result with current orders/positions
        v
Bybit
```

The repository currently contains only the architecture and contract boundaries that have been agreed. Runtime v1 binds each active spec only to its explicitly supplied `ticker + timeframe` base stream; non-base stream readiness is a documented limitation. Implementation structure, persistence, retries, idempotency, deployment, and framework choices are intentionally not fixed yet.

Documents:

- `docs/architecture/intent.md`
- `docs/architecture/system-interactions.md`
- `docs/architecture/contracts.md`

## Architecture documents

- `docs/architecture/intent.md`
- `docs/architecture/system-interactions.md`
- `docs/architecture/contracts.md`
- `docs/architecture/open-questions.md`
- `docs/architecture/api-and-data-structure-audit.md`
- `docs/architecture/implementation-gates.md`
- `docs/architecture/runtime-journal.md`

## Pre-implementation gate

`Implementation Gate 01` is mandatory: before Strategy Runtime implementation begins, the Strategy Engine runtime-facing request and neutral current-point response contracts must be designed and approved. See `docs/architecture/api-and-data-structure-audit.md`.

## Cross-repository gates

Strategy Runtime implementation is blocked by explicit gates for Strategy Engine contract adaptation, ABI current-point reconciliation and execution-lifecycle audit, MDS stream-state transition notification, ABI scoped cancellation, and recovery after a stream returns to `ready`. See `docs/architecture/implementation-gates.md`.

## V1 activation behaviour

- Deactivating a strategy removes it from future Engine routing and requests cancellation of its pending entry orders in ABI.
- Open positions and their protective orders are preserved.
- Reactivating a strategy does not trigger an immediate calculation in v1; it waits for the next webhook of its configured base stream.

## V1 file-backed registry

- Strategy specs are discovered from a configured folder.
- A separate JSON activation registry persists `is_active` overrides.
- A newly discovered spec receives `is_active=true` by default during the next webhook reconciliation.
- Explicit API deactivation persists across restarts and overrides that default.
- Manual spec-file removal is observed only on the next MDS webhook reconciliation.
- V1 has no managed delete operation; the future lifecycle is `deactivate via is_active -> cancel pending entries -> delete through API/frontend -> remove file`.
- Runtime v1 has no standalone semantic spec validator; the initial smoke test relies on specs prepared and validated by the existing Workbench/frontend or CLI path. Extraction of an independent configurator/validator is tracked as an implementation gate.
- `strategy_id` identifies a strategy family, `instance_id` is the stable live-instance key used by the activation registry, and `config_hash` fingerprints the current configuration without controlling activation.
## V1 runtime journal

- Runtime writes typed append-only JSONL events rather than free-form text records.
- One incoming webhook creates one `flow_id`; the semantic path is represented by multiple immutable events linked by that flow.
- Events are classified as `trading` or `technical` and carry an independent severity.
- The local journal is a future-compatible event source for a standalone Central Journal, but it is not used to restore Runtime state.
- Runtime journals only its own orchestration boundaries; Engine internals remain in Strategy Engine and exchange execution remains in ABI.


- [Architecture master plan](docs/architecture/master-plan.md)
