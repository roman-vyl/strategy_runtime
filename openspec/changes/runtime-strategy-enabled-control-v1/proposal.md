## Why

`enabled` of a strategy lives only in its deployment file, which Runtime mounts read-only. To switch a strategy off, the owner edits a file by hand. Worse, a strategy switched off while it has an entry order on the exchange is simply no longer processed: the order stays and nobody manages it. The dashboard needs a switch, and the switch needs Runtime to handle orders and positions safely.

## What Changes

- New HTTP route `PUT /v1/strategy-instances/{strategy_instance_id}/enabled` with body `{"enabled": true|false}`.
- The deployment JSON stays the only source of truth for `enabled`. After the checks and ABI actions, Runtime replaces the file atomically, changing only `enabled`. No separate store, no seeding, no new state.
- Bar selection and `GET /v1/strategy-instances` are unchanged: they already read the file on every bar and every request.
- Disable is safe by construction, decided under the instance's mutex against ABI, and the file is written last:
  - recovery pending, or a position open: refused with `409` and a reason, nothing changes;
  - an entry order on the exchange: Runtime sends the existing corrective CANCEL, and only an exact `absent` confirmation clears the cycle and then writes the file; anything else leaves the file untouched;
  - nothing open: the file is written at once.
- Enable only writes the file.
- The write refuses when the file changed since it was read, or when the strategy identity would change.
- The specs mount becomes writable for Runtime, for this one purpose only. **BREAKING (boundary):** lifts the 2026-10-16 rule "Runtime is a read-only consumer" for the single field `enabled`.
- No change to Engine, ABI, state schema, journal events, recovery or Research (Research stays create-only with `enabled: false`).

## Capabilities

### New Capabilities

- `strategy-enabled-control`: the route, the disable decision table, the atomic single-field file write and its refusals.

### Modified Capabilities

- `strategy-runtime-docker`: specs mount writable, for the enabled change only.

## Impact

`adapters/http`, a new service in `runtime/`, a small file writer in `utility/deployment_catalog`, production composition; `docker-compose.yml` of strategy_runtime and bbb_stack (specs mount, separate PR in bbb_stack). Frontend switch is a separate change in `research_frontend`. Mac smoke of the bind mount is required before apply.
