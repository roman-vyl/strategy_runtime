# Strategy Runtime

Strategy Runtime is BBB's live orchestration service between market-data
closed-bar notifications, Strategy Engine calculations, and ABI execution. It
owns per-strategy runtime state and serializes all state writers for one
`strategy_instance_id`.

Runtime does not implement strategy calculations, exchange execution, durable
recovery, retries, or multi-process state coordination.

## Production architecture

```text
MDS POST /v1/webhooks/closed-bar
  -> bounded CommittedBarIntakeBoundary
  -> single CommittedBarIntakeWorker
  -> CommittedBarOrchestrator
       -> filesystem deployment catalog
       -> instrument/timeframe selector
       -> deterministic per-instance fan-out
  -> StrategyCycleHandoffBoundary
  -> StrategyRuntimeOrchestrator
       -> keyed mutex
       -> in-memory state repository
       -> ABI open-position lookup when a current trade cycle exists
       -> StrategyUseCaseRouter
            no open position -> Engine live-entry
                             -> EntryReconciliationOrchestrator
                             -> ABI entry-package
            open position    -> first-fill freeze when required
                             -> Engine open-trade
                             -> PositionManagementOrchestrator
                             -> ABI protection or close
       -> save confirmed state changes
```

ABI reports the first execution fill through a separate synchronous endpoint:

```text
ABI PUT /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill
  -> AbiExecutionEventOrchestrator
  -> the same keyed mutex and in-memory repository
  -> idempotent first-fill state transition
```

The shared mutex prevents a closed-bar cycle and first-fill callback from
writing the same strategy instance concurrently. The lock intentionally covers
the complete Engine/ABI cycle in Live V1.

## State and save semantics

`StrategyInstanceRuntimeState` is the repository-owned aggregate. Its optional
`CurrentTradeCycle` records the ABI-confirmed entry package, frozen first-fill
context, and latest confirmed management protection.

State is immutable and saved only after acknowledged facts:

- a new or changed entry package is saved after ABI confirmation;
- the first observation of an open position may perform a dedicated first-fill
  save before open-trade projection;
- a later protection or close result may perform a separate post-projection
  save after ABI confirmation;
- no-op transitions do not write.

Consequently, the first bar that observes a fill can legitimately make two
saves: one for first-fill freeze and one for the confirmed management result.

The repository and intake queue are process-local and non-durable. Production
must run one process, one worker, and one replica. Restart recovery and
multi-replica coordination are outside Live V1.

## HTTP surface

```text
GET  /health/live
GET  /health/ready
POST /v1/webhooks/closed-bar
PUT  /v1/strategy-instances/{strategy_instance_id}/trade-cycles/{trade_cycle_id}/first-fill
```

The closed-bar endpoint acknowledges an event once it enters the bounded queue;
the response does not imply that strategy processing or execution succeeded.
Processing outcomes are written to the JSONL journal.

## Configuration

See [`config/runtime.env.example`](config/runtime.env.example) for the complete
environment surface:

- bind host and port;
- deployment-spec directory;
- processing-journal path;
- Strategy Engine and ABI base URLs;
- bounded outbound timeouts;
- committed-bar queue capacity.

Deployment files are flat JSON documents containing `enabled`, `ticker`,
`base_timeframe`, `strategy_id`, and `raw_spec`. Runtime derives
`strategy_instance_id` deterministically from the semantic deployment payload.

## Local development

Python 3.12 is required.

```bash
make install-dev
make run
```

`make run` starts the sole production composition root exposed by the
`strategy-runtime` package entrypoint.

## Verification

```bash
make verify
```

The verification target runs lint, format checking, type checking, and tests.
Run strict OpenSpec validation separately with
`npm exec -- openspec validate --all --strict`. Some ABI contract tests expect
`abi_executor_bot` to be checked out beside this repository.

Current capability contracts live in [`openspec/specs/`](openspec/specs).
Completed change records remain immutable under
[`openspec/changes/archive/`](openspec/changes/archive).
