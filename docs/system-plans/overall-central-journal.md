# Overall Central Journal — deferred system plan

Status: future cross-service initiative; not part of the active Strategy Runtime implementation sequence.

Create a standalone Overall Central Journal for the financially responsible live trading path.

Participating modules:

- Market Data Service;
- Strategy Runtime;
- Strategy Engine;
- ABI Executor.

Each module should eventually emit typed, timestamped events within its own responsibility boundary, with compatible correlation semantics so a live flow can be reconstructed across service seams. The Central Journal would receive, store, order, filter, correlate, and present those events as trading and technical views.

Backtest-only modules, including Research Service, are outside this integration scope because they do not own live financial decisions or exchange execution.

Runtime's local JSONL journal is an early implementation of a local event envelope, not the Central Journal and not a durable lifecycle store. This system plan remains open until the standalone journal service and cross-module event contracts are separately designed and verified.
