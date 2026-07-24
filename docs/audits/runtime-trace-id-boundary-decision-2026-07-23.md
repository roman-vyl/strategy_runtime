# Runtime trace ID boundary decision — 2026-07-23

## Decision

The former `flow_id` is renamed to `trace_id`. Runtime HTTP ingress generates one `trace_id` for each accepted committed-bar request, but the current implementation immediately discards it.

`trace_id` MUST NOT be included in:

- background-use-case arguments;
- `CommittedBarProcessingContext` or any replacement context object;
- `StrategyBarProcessingUnit`;
- processing journal events;
- orchestration results or typed failures;
- `StrategyInstanceRuntimeState`;
- Runtime → Engine or Runtime → ABI payloads.

The generator remains as a dormant observability hook until a real tracing subsystem such as OpenTelemetry is designed.
