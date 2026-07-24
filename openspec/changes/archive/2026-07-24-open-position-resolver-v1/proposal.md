## Why

After obtaining one `StrategyInstanceRuntimeState`, Runtime must learn whether
ABI currently has an open position for that strategy instance before choosing
an Engine projection path. Local recipe or trade-cycle presence is not
authoritative for that fact.

The ABI boundary remains narrow: it receives only `strategy_instance_id` and
returns the current position fact plus the execution facts needed by an
open-trade projection.

## What Changes

- add scalar `OpenPositionResolver.resolve(state)`;
- process every supplied state without filtering by local lifecycle data;
- send exactly one identity-only lookup request;
- require an exact boolean `position_open`;
- validate the open/closed execution-fact combinations;
- distinguish typed transport unavailability from malformed protocol data;
- return one transient position-resolved state view;
- keep routing, Engine calls, state mutation, ABI implementation, and lifecycle
  reconciliation outside this change.

## Capabilities

### New Capabilities

- `open-position-resolver`: Resolves current ABI open-position facts for one
  strategy-instance runtime state.

### Modified Capabilities

None.

## Impact

- Adds the scalar Runtime step between state get-or-create and use-case routing.
- Adds an ABI-facing lookup port whose request contains only
  `strategy_instance_id`.
- Adds typed unavailable and protocol failures at the ABI adapter contract.
- Does not persist returned position facts or implement an ABI HTTP adapter.
