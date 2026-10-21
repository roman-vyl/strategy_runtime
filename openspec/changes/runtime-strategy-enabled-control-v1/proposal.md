## Why

`enabled` of a strategy lives only in its spec file on the Mac, which Runtime mounts read-only. To switch a strategy off, the owner edits a file by hand. Worse, a strategy switched off while it has an entry order on the exchange is simply no longer processed: the order stays and nobody manages it. The dashboard needs a switch, and the switch needs Runtime to own the decision and handle orders and positions safely.

## What Changes

- New HTTP route `PUT /v1/strategy-instances/{strategy_instance_id}/enabled` with body `{"enabled": true|false}`.
- Runtime keeps its own durable `enabled` overrides (append-only JSONL beside the state store). The effective value is the override if present, otherwise the spec file's `enabled`. The file stays read-only and is only the initial value.
- Bar selection and `GET /v1/strategy-instances` use the effective value. **BREAKING (meaning):** `enabled` in the list is no longer "the value in the spec file".
- Disable is safe by construction, decided under the instance's mutex against ABI:
  - recovery pending, or a position open: refused with `409` and a reason, nothing changes;
  - an entry order on the exchange: Runtime sends the existing corrective CANCEL, and only an exact `absent` confirmation clears the cycle and disables; anything else leaves the strategy enabled;
  - nothing open: disabled at once.
- Enable only writes the override.
- No change to Engine, ABI, state schema, journal events or recovery.

## Capabilities

### New Capabilities

- `strategy-enabled-control`: the route, the override store, the disable decision table, effective `enabled`.

### Modified Capabilities

- `strategy-instance-list`: `enabled` is the effective value.

## Impact

`adapters/http`, a new service in `runtime/`, a small JSONL store in `infrastructure/`, production composition, bar selection input. Frontend switch is a separate change in `research_frontend`.
