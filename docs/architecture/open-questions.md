# Open Architectural Questions

This document records agreed architectural direction without prematurely choosing an implementation.

## Strategy specification storage and runtime activation

Two distinct concepts are expected in the future architecture.

### Strategy Specification

A Strategy Specification answers:

> What should be calculated?

Strategy specs are expected to have a physical storage layer. A file-backed store is a likely initial form, but the final storage mechanism is not yet fixed.

Possible future implementations include files, a database, or a dedicated strategy registry.

### Runtime Strategy Activation

Runtime activation answers:

> Should this strategy spec be executed in live runtime now?

The runtime model is expected to include an `is_active` semantic.

A future Runtime frontend is expected to allow an operator to enable and disable strategies while the system is running.

This separates:

```text
Strategy Specification
        |
        | what should be calculated
        v
Runtime Activation
        |
        | whether it is active now
        v
Strategy Runtime
```

## Still open

The following decisions remain open:

- who owns the authoritative list of strategy specs;
- where strategy spec files are physically stored;
- who owns the authoritative `is_active` value;
- whether activation belongs to Strategy Runtime, a Strategy Registry, or a separate Control Plane;
- how the future Runtime frontend reads and changes activation state;
- whether one spec can have multiple live runtime instances for different instruments or timeframes;
- how activation state is persisted and recovered.

No implementation choice is implied by this document.

## Future immediate calculation on activation

The desired future user experience may include calculating a strategy immediately when `is_active` changes from `false` to `true`, rather than waiting for the next base-stream bar.

This is not part of v1. It would require an additional calculation trigger path that does not originate from the MDS closed-bar webhook.

Before such a feature can be approved, the architecture must define:

- who emits the out-of-band calculation request;
- whether the calculation may create a live trading intent immediately;
- how it is distinguished from ordinary bar-triggered evaluation;
- how duplicate or concurrent activation and bar events are handled;
- what readiness assumptions apply at the time of activation.

Until that review is completed, reactivation waits for the next normal webhook of the configured base stream.

## File-registry details still to decide

The v1 direction is now agreed: a spec directory records available definitions, while a separate JSON activation registry persists `is_active`; first discovery during webhook reconciliation defaults to active.

The stable activation identity is now agreed: `instance_id` is the activation-registry key, while `config_hash` fingerprints the current configuration. The following implementation details remain open:

- retention or tombstone semantics for activation records after the future managed delete operation;
- behaviour when a file is renamed or later restored;
- exact API and filesystem transaction semantics for the ordered `deactivate -> delete` lifecycle;
- whether an edited file becomes effective on the next webhook or requires explicit reload;
- atomic JSON update and backup/recovery rules;
- concurrency between webhook reconciliation and HTTPS activation updates;
- how parse and Engine-validation failures are exposed to operators.


## ABI per-bar reconciliation contract

The Runtime-side target is fixed: every successful current-point result for each permitted instance is handed to ABI on every triggering bar. The remaining open question is implementation compatibility at the ABI boundary, not whether Runtime filters unchanged results. Gate 02 must audit and close the ABI desired-state, no-op, replacement, protection-update, idempotency, and acceptance semantics.
