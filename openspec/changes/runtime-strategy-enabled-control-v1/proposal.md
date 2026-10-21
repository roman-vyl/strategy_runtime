## Why

`enabled` of a strategy lives only in its spec file on the Mac, which Runtime mounts read-only. To switch a strategy off, the owner edits a file by hand. Worse, a strategy switched off while it has an entry order on the exchange is simply no longer processed: the order stays and nobody manages it. The dashboard needs a switch, and the switch needs Runtime to own the decision and handle orders and positions safely.

## What Changes

- New HTTP route `PUT /v1/strategy-instances/{strategy_instance_id}/enabled` with body `{"enabled": true|false}`.
- Runtime keeps its own durable `enabled` value per strategy (append-only JSONL beside the state store). The spec file's `enabled` is read exactly once per strategy, when Runtime first sees it: that value is written down and the file is never consulted for `enabled` again. The file stays read-only.
- Bar selection and `GET /v1/strategy-instances` use the stored value. **BREAKING (meaning):** `enabled` in the list is no longer "the value in the spec file"; editing it in a file Runtime has already seen changes nothing.
- Disable is safe by construction, decided under the instance's mutex against ABI:
  - recovery pending, or a position open: refused with `409` and a reason, nothing changes;
  - an entry order on the exchange: Runtime sends the existing corrective CANCEL, and only an exact `absent` confirmation clears the cycle and disables; anything else leaves the strategy enabled;
  - nothing open: disabled at once.
- Enable only writes the stored value.
- No change to Engine, ABI, state schema, journal events or recovery.

## Capabilities

### New Capabilities

- `strategy-enabled-control`: the route, the stored value and its one-time seeding from the spec file, the disable decision table.

### Modified Capabilities

- `strategy-instance-list`: `enabled` is Runtime's stored value.

## Impact

`adapters/http`, a new service in `runtime/`, a small JSONL store in `infrastructure/`, production composition, bar selection input. Frontend switch is a separate change in `research_frontend`.
