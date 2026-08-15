## ADDED Requirements

### Requirement: Resolution runs independently of committed-bar cadence
Strategy Runtime SHALL provide a background component that attempts to
resolve every instance's non-null `pending_entry_recovery` on a bounded
interval, independent of `CommittedBarIntakeWorker` and of whether any
committed bar has arrived for that instance's instrument/timeframe.

#### Scenario: Resolution proceeds without a new committed bar
- **WHEN** an instance has a non-null `pending_entry_recovery` and no new
  committed bar has arrived for its instrument/timeframe
- **THEN** the resolver still attempts to resolve that instance on its own
  polling interval

#### Scenario: Resolution is not gated on any specific timeframe
- **WHEN** an instance's deployment timeframe is 1h or 1d
- **THEN** resolution attempts still occur on the resolver's own bounded
  interval, not on that deployment's bar cadence

### Requirement: One attempt is a single bounded read, under the shared keyed mutex
Each resolution attempt for one `strategy_instance_id` SHALL acquire
`StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)` — the same
registry `StrategyRuntimeOrchestrator` and the first-fill webhook path
already share — for its full duration, and SHALL perform at most one bounded
ABI recovery-state query plus, in exactly one case, one bounded corrective
CANCEL call.

#### Scenario: Attempt acquires the same registry bar processing uses
- **WHEN** the resolver attempts to resolve one instance
- **THEN** it holds `StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)`
  for the duration of that attempt
- **AND** a concurrent committed-bar invocation or first-fill webhook call
  for the same instance cannot interleave with it

#### Scenario: A resolved instance is invisible to a concurrent attempt
- **WHEN** the resolver acquires the mutex for an instance whose
  `pending_entry_recovery` was already cleared by another caller before this
  attempt started
- **THEN** the attempt reads the current state, finds
  `pending_entry_recovery` null, and returns without querying ABI

#### Scenario: Different instances resolve independently
- **WHEN** two different instances both have a non-null
  `pending_entry_recovery`
- **THEN** their resolution attempts do not block each other

### Requirement: Resolution applies no wall-clock gate of any kind
The resolver SHALL NOT compare any timestamp to the current time, SHALL NOT
compute an age or elapsed duration for `pending_entry_recovery`, and SHALL
NOT withhold, skip, or alter an ABI query on the basis of how long a marker
has been pending. Whether an attempt can resolve depends entirely on ABI's
response — specifically, whether it is one of the four positive
`recovery_state` values below — never on elapsed time.

#### Scenario: Every attempt queries ABI regardless of how long the marker has been pending
- **WHEN** the resolver attempts to resolve an instance whose
  `pending_entry_recovery` has persisted across many prior unresolved
  attempts
- **THEN** the resolver queries ABI exactly the same way it would for a
  marker set moments ago — no different code path, no skipped query, no
  escalation to a different outcome based on elapsed time

### Requirement: An uncertain Apply resolves by the four ABI-reported states
When `pending_entry_recovery` is non-null and `current_trade_cycle` is null,
the resolver SHALL apply the following resolution table to ABI's
`recovery_state` response.

#### Scenario: entry_order_live or position_open reconstructs the cycle
- **WHEN** ABI reports `entry_order_live` or `position_open`
- **THEN** the resolver builds a `CurrentTradeCycle` for
  `pending_entry_recovery.trade_cycle_id` from the response's
  `applied_entry_package`
- **AND**, for `position_open`, additionally freezes the first-fill context
  from the response's fill facts, using the same transition
  `first-fill-transition` already defines
- **AND** durably saves the reconstructed state with
  `pending_entry_recovery = null`

#### Scenario: terminal_without_fill or terminal_after_fill forgets the attempt
- **WHEN** ABI reports `terminal_without_fill` or `terminal_after_fill`
- **THEN** the resolver durably saves `current_trade_cycle = null`,
  `pending_entry_recovery = null`
- **AND** does not resend CREATE and does not attempt to reconstruct or
  revive the original desired entry
- **AND** a later committed bar's ordinary reconciliation decides afresh
  whether to apply a new entry

### Requirement: An uncertain removal resolves by the four ABI-reported states, with one corrective action
When `pending_entry_recovery` is non-null and `current_trade_cycle` holds the
trade cycle being removed, the resolver SHALL apply the following resolution
table.

#### Scenario: terminal_without_fill or terminal_after_fill confirms the removal
- **WHEN** ABI reports `terminal_without_fill` or `terminal_after_fill`
- **THEN** the resolver durably saves `current_trade_cycle = null`,
  `pending_entry_recovery = null`

#### Scenario: position_open means the removal lost the race to a fill
- **WHEN** ABI reports `position_open`
- **THEN** the resolver durably saves `pending_entry_recovery = null`,
  leaving `current_trade_cycle` exactly as it was
- **AND** does not attempt to reverse, cancel, or otherwise act on the now-open
  position — the ordinary bar path's open-position resolution and position
  management take over on the next eligible bar

#### Scenario: entry_order_live triggers the only corrective action this component performs
- **WHEN** ABI reports `entry_order_live`
- **THEN** the resolver issues one bounded CANCEL for
  `pending_entry_recovery.trade_cycle_id`
- **AND** does not modify `pending_entry_recovery` — it remains set for a
  later attempt to observe the outcome
- **AND** issues no other command (no CREATE, no amend, no resend of any
  desired entry)

### Requirement: A transport failure, availability failure, inconclusive-evidence response, or unknown-binding response all change nothing
When the ABI recovery-state query itself does not return one of the four
positive `recovery_state` values — a timeout, network failure, protocol
error, an ABI-reported availability failure, ABI's own safe-error response
for insufficient positive evidence (see `entry-cycle-recovery-resolution`:
absence of evidence is never treated as evidence of absence), or ABI's `422
unknown_trade_cycle_binding` public error — the resolver SHALL NOT modify
`pending_entry_recovery` and SHALL NOT treat any of these as evidence of any
`recovery_state`, including `terminal_without_fill`. All of these are
handled by exactly the same code path: leave the marker untouched, retry
next tick. `unknown_trade_cycle_binding` is deliberately not special-cased
into `terminal_without_fill` on the Runtime side: if ABI can safely prove
absence for a binding it does not recognize, that proof must be expressed as
one of ABI's own documented `recovery_state` values (see the paired ABI
capability), not inferred by Runtime from an HTTP status.

#### Scenario: A failed or inconclusive query leaves the marker untouched
- **WHEN** the ABI recovery-state client raises for this attempt, or returns
  its safe-error response instead of a `recovery_state`, for any of the
  reasons above
- **THEN** the resolver durably changes nothing
- **AND** the same instance is eligible for another attempt on the next
  interval
- **AND** the resolver does not distinguish "ABI could not be reached" from
  "ABI answered but could not positively establish an outcome" — both leave
  `pending_entry_recovery` exactly as it was

#### Scenario: An unknown trade-cycle binding is not treated as terminal_without_fill
- **WHEN** ABI returns `422 unknown_trade_cycle_binding` for the queried
  `trade_cycle_id`
- **THEN** the resolver treats this identically to any other failed query
- **AND** does not save `current_trade_cycle = null` or
  `pending_entry_recovery = null` on the basis of this response alone

### Requirement: The resolver never initiates Engine evaluation or position management
The resolver SHALL NOT call `StrategyUseCaseRouter`, Strategy Engine,
`EntryReconciliationOrchestrator`, or `PositionManagementOrchestrator`, even
when a resolution discovers a fill. It is strictly write-only with respect to
`pending_entry_recovery` and the minimal state needed to represent the
resolved fact; initiating management remains the ordinary committed-bar
pipeline's responsibility.

#### Scenario: A discovered fill does not trigger immediate management
- **WHEN** a resolution attempt discovers `position_open`
- **THEN** the resolver saves the resolved state and returns
- **AND** does not call the use-case router, Strategy Engine, or
  `PositionManagementOrchestrator` as part of this attempt
- **AND** the next committed bar's ordinary open-position resolution and
  routing discover the open position and proceed through the normal
  position-management pipeline

### Requirement: The background worker follows the existing intake-worker lifecycle shape
Strategy Runtime SHALL provide a background worker that drives resolution
attempts on a fixed, bounded polling interval, using the same lifecycle shape
as `CommittedBarIntakeWorker`: an explicit state machine, `start()`/
`stop_once()` with `join()`, and per-attempt exception isolation that logs
and continues rather than stopping the loop. No adaptive or exponential
backoff is required for V1; a generic retry/backoff framework is out of
scope for this component.

#### Scenario: One tick attempts every currently pending instance
- **WHEN** the worker's interval elapses
- **THEN** it enumerates pending instances via
  `list_ids_with_pending_entry_recovery()` and attempts resolution for each
- **AND** a failure resolving one instance does not prevent attempting the
  others in the same tick

#### Scenario: No tight busy-loop
- **WHEN** the worker is running
- **THEN** it sleeps for a fixed, bounded interval between ticks
- **AND** that interval does not shrink to zero or otherwise become a tight
  poll, regardless of how many instances are pending or how many attempts
  failed on the previous tick
- **AND** the interval does not grow or shrink adaptively between ticks —
  a fixed interval is sufficient for V1

#### Scenario: Startup requires no separate recovery step
- **WHEN** the process starts
- **THEN** the worker begins ticking against whatever
  `pending_entry_recovery` markers `JsonlStrategyInstanceRuntimeStateRepository`'s
  existing startup replay already restored
- **AND** process readiness does not wait for any outstanding
  `pending_entry_recovery` to resolve

#### Scenario: Graceful shutdown joins an in-flight attempt before closing ABI clients
- **WHEN** the process shuts down
- **THEN** the worker stops scheduling new attempts and joins any in-flight
  bounded attempt
- **AND** this completes before the ABI HTTP client used by the resolver is
  closed
