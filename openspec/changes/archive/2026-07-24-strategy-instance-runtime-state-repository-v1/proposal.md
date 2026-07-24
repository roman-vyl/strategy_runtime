## Why

The semantic Runtime pipeline needs one state aggregate for each derived strategy
instance during the lifetime of its repository. A deterministic get-or-create
boundary prevents each committed-bar invocation from constructing unrelated
state for the same `strategy_instance_id`.

## What Changes

- define `StrategyInstanceRuntimeStateRepository.get_or_create(...)`;
- accept one typed request mapped from `StrategyBarProcessingUnit`;
- use the utility-derived `strategy_instance_id` as the repository key;
- preserve the first registered instrument, base timeframe, raw specification,
  and source path in an immutable snapshot;
- let the request transport `raw_spec` and make `RegisteredSpecSnapshot`
  responsible for validation, detachment, and recursive freezing;
- create missing state with `current_trade_cycle = null`;
- return existing state without mutation;
- make in-process creation atomic and idempotent for repeated or concurrent
  equivalent calls;
- reject reuse of one `strategy_instance_id` for a different `strategy_id`;
- treat the derived identity as authoritative without repeating field-by-field
  comparison of identity-bearing deployment data;
- keep state updates, recipe lifecycle, Engine calls, ABI calls, and physical
  persistence outside this capability.

## Capabilities

### New Capabilities

- `strategy-instance-runtime-state-repository`: Gets or atomically creates the
  Runtime state aggregate for one utility-derived strategy instance.

### Modified Capabilities

None.

## Impact

- Runtime state models under `src/strategy_runtime/runtime/state/`.
- Semantic orchestration in
  `src/strategy_runtime/runtime/orchestrator/orchestrator.py`.
- An in-memory `RLock`-protected repository implementation.
- No physical storage contract or durability guarantee.
- No change to utility identity derivation, Strategy Engine, ABI, or exchange
  behavior.
