## Why

The dashboard can switch a strategy off but cannot remove it. A strategy that is no longer wanted (a failed candidate, a test export) stays in the list for good; the only way out is to delete its deployment file by hand on the Mac. Removing a file by hand while the strategy holds an order or a position is dangerous: Runtime stops managing them, so the owner needs a delete that Runtime performs with the same safety as the disable.

## What Changes

- New HTTP route `DELETE /v1/strategy-instances/{strategy_instance_id}`, no body.
- "Delete" means **move to the trash, not erase**: the deployment file moves to the hidden subdirectory `.deleted/` of the specs directory under the name `<stem>.<UTC time>.json`. Runtime and Research scan only top-level `*.json` files of the directory, so they no longer see the strategy; restoring is moving the file back by hand. Erasing from the trash is out of scope.
- Delete is allowed only for a strategy whose file says `enabled: false`; otherwise it is refused with `still_enabled`.
- Division of work: the disable stops a strategy safely; the delete removes a strategy that is already safely stopped. A strategy switched off through the route has no recovery marker and no trade cycle, so in the normal path the delete makes no ABI call.
- The disable's checks are repeated under the instance's mutex as a safety net, because `enabled: false` is only text on disk: a file can be edited by hand or a state can be inconsistent after an older Runtime version while a cycle or an entry order is still there. Before the strategy becomes invisible to Runtime: pending recovery, an open position and an unsettled closure are refused; a resting entry order is cancelled through ABI and only an exact `absent` lets the delete continue; the state is saved without a current trade cycle; the file moves last.
- The state record in the runtime state store and the events in the Journal stay as they are.
- No change to Engine, ABI, Research, the state schema, compose files or the deployment file format. The specs mount is already writable (`bbb-runtime-specs-writable-v1`).

## Capabilities

### New Capabilities

- `strategy-delete`: the route, the decision table, the trash move and its refusals.

### Modified Capabilities

None. The enable route and the list route are unchanged.

## Impact

`adapters/http`, a new service in `runtime/`, a small trash-move component beside the enabled writer in `utility/deployment_catalog`, production composition. Frontend button is a separate change in `research_frontend`. Mac smoke of the hidden subdirectory on the bind mount is required before apply.
