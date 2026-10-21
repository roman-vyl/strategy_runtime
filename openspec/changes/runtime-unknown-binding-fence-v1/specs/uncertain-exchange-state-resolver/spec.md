## ADDED Requirements

### Requirement: An unknown binding during an uncertain APPLY is fenced by one corrective CANCEL
When `pending_entry_recovery` is non-null, `current_trade_cycle` is null, and the
recovery-state query fails with `422 unknown_trade_cycle_binding`, the resolver SHALL send
exactly one bounded corrective CANCEL (`desired_entry: null`) for the same strategy
instance and the marker's `trade_cycle_id`, and SHALL clear the marker only when that
CANCEL returns `EntryPackageAbsent` with exactly matching identity.

#### Scenario: ABI fences the unknown pair
- **WHEN** the query returns `unknown_trade_cycle_binding` and the CANCEL returns
  `EntryPackageAbsent` for the same strategy instance and trade cycle
- **THEN** the resolver durably saves `current_trade_cycle: null` and
  `pending_entry_recovery: null`
- **AND** sends no CREATE and reconstructs no desired entry

#### Scenario: CANCEL does not prove absence
- **WHEN** the CANCEL fails, times out, or returns any other result or a mismatched
  identity
- **THEN** the resolver changes no state and retries only on a later tick after a fresh
  query

#### Scenario: Unknown binding during an uncertain removal
- **WHEN** the query returns `unknown_trade_cycle_binding` while `current_trade_cycle` is
  non-null
- **THEN** the resolver sends no CANCEL and changes no state

#### Scenario: The 422 alone never clears the marker
- **WHEN** the query returns `unknown_trade_cycle_binding`
- **THEN** no state change happens on the basis of that response alone

#### Scenario: Delayed original PUT after release
- **WHEN** the marker was cleared through this row and the original non-null PUT for the
  same trade cycle reaches ABI afterwards
- **THEN** no exchange order is created for that trade cycle

## MODIFIED Requirements

### Requirement: A transport failure, availability failure, inconclusive-evidence response, or unknown-binding response all change nothing
When the ABI recovery-state query does not return a positive `recovery_state` — a
timeout, network failure, protocol error, ABI availability failure, ABI's safe error for
insufficient evidence, or `422 unknown_trade_cycle_binding` — the resolver SHALL NOT
modify state on the basis of that response and SHALL NOT treat it as any
`recovery_state`, including `terminal_without_fill`. The only follow-up any of these may
trigger is the fencing CANCEL for `unknown_trade_cycle_binding` during an uncertain APPLY,
and only its exact `EntryPackageAbsent` may clear the marker.

#### Scenario: A failed or inconclusive query leaves the marker untouched
- **WHEN** the ABI recovery-state client raises for this attempt with anything other than
  `unknown_trade_cycle_binding`, or returns its safe-error response
- **THEN** the resolver durably changes nothing and sends no CANCEL
- **AND** the same instance is eligible for another attempt on the next interval

#### Scenario: An unknown trade-cycle binding is not treated as terminal_without_fill
- **WHEN** ABI returns `422 unknown_trade_cycle_binding` for the queried `trade_cycle_id`
- **THEN** the resolver does not save `current_trade_cycle = null` or
  `pending_entry_recovery = null` on the basis of this response alone
