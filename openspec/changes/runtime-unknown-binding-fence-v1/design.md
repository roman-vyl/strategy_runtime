## Context

`resolver.attempt()` catches every `AbiEntryCycleRecoveryClientError` and returns,
including `AbiEntryCycleRecoveryUnknownTradeCycleBinding` (422). The resolver already owns
`_cancel_and_clear_only_if_exact_absent(state, trade_cycle_id)`, used for
`entry_order_not_found` (uncertain APPLY) and `entry_order_live` (uncertain removal):
one CANCEL, clear only on exact `EntryPackageAbsent`.

ABI (after `abi-unknown-pair-recovery-tombstone-v1`): a CANCEL for a pair with no record
durably writes `absent` with `mutation_fenced: true` under the pair lock and returns
`entry_package_absent`; a later non-null PUT for that pair is refused without any exchange
call; a repeated CANCEL returns `entry_package_absent` again.

## Decisions

### D1. Catch the 422 type separately, only in the APPLY branch

```
try: response = query(...)
except AbiEntryCycleRecoveryUnknownTradeCycleBinding:
    if state.current_trade_cycle is None:
        self._cancel_and_clear_only_if_exact_absent(state, trade_cycle_id)
    return
except AbiEntryCycleRecoveryClientError:
    return
```

All other client errors keep today's behavior. Uncertain removal with 422 keeps today's
behavior: a cycle Runtime already holds must have an ABI record; a 422 there is an
inconsistency, not a lost PUT.

### D2. Why this is not inference from 422

Runtime clears only on ABI's positive, durable, identity-matched `EntryPackageAbsent`.
The pair lock in ABI serializes the CANCEL against a PUT that is still being processed:
if the PUT holds the lock, the CANCEL waits and then sees the PUT's own record and goes
through the existing CANCEL semantics (cancel a live order, or confirm absence). If the
PUT has not reached ABI yet, the fence makes it harmless when it arrives.

### D3. Bounded

At most one recovery-state query and one CANCEL per attempt (unchanged bound). The CANCEL
uses the existing entry-package timeout. A failed CANCEL is retried only on a later tick,
after a fresh query.

## Risks

- Deploying this before the ABI fence reopens the delayed-PUT race. Mitigation: deployment
  order in the proposal; the Runtime task list checks the deployed ABI version first.
- One extra CANCEL per 30 s tick while ABI is down: same load as today's query loop.

## Acceptance

Mandatory end-to-end test (with ABI fake or ABI integration): Runtime marker for cycle C,
ABI has no record → resolver sends CANCEL → marker cleared → the original non-null PUT for
C arrives afterwards → ABI creates no order and the pair stays `absent`.
