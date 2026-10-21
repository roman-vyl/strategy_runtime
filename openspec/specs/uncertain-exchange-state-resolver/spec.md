# uncertain-exchange-state-resolver Specification

## Purpose

TBD - Update Purpose after archive: the background worker that resolves
`pending_entry_recovery` against ABI's recovery-state endpoint, independent of
committed-bar cadence, under the shared keyed mutex.
## Requirements
### Requirement: Resolution runs independently of committed-bar cadence
Strategy Runtime SHALL provide a background component that attempts to
resolve every instance's non-null `pending_entry_recovery` or
`pending_close_recovery` on a bounded interval, independent of
`CommittedBarIntakeWorker` and of whether any committed bar has arrived for
that instance's instrument/timeframe.

#### Scenario: Resolution proceeds without a new committed bar
- **WHEN** an instance has a non-null `pending_entry_recovery` or
  `pending_close_recovery` and no new committed bar has arrived for its
  instrument/timeframe
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
already share — for its full duration. An entry-recovery attempt SHALL
perform at most one bounded ABI recovery-state query plus, in exactly one
case, one bounded corrective CANCEL call. A close-recovery attempt SHALL
perform at most one bounded corrective `close_position` re-issue call, per
"An uncertain close resolves by re-issuing the close command".

#### Scenario: Attempt acquires the same registry bar processing uses
- **WHEN** the resolver attempts to resolve one instance, for either an
  entry-recovery or a close-recovery marker
- **THEN** it holds `StrategyInstanceKeyedMutexRegistry.hold(strategy_instance_id)`
  for the duration of that attempt
- **AND** a concurrent committed-bar invocation or first-fill webhook call
  for the same instance cannot interleave with it

#### Scenario: A resolved instance is invisible to a concurrent attempt
- **WHEN** the resolver acquires the mutex for an instance whose
  `pending_entry_recovery` or `pending_close_recovery` was already cleared by
  another caller before this attempt started
- **THEN** the attempt reads the current state, finds the corresponding
  marker null, and returns without querying or mutating ABI

#### Scenario: Different instances resolve independently
- **WHEN** two different instances both have a non-null
  `pending_entry_recovery` or `pending_close_recovery`
- **THEN** their resolution attempts do not block each other

#### Scenario: No attempt sends more than one corrective command
- **WHEN** either eligible corrective row is observed
- **THEN** the attempt sends at most one CANCEL and never sends CREATE or amend

### Requirement: Resolution applies no wall-clock gate of any kind
The resolver SHALL NOT compare any timestamp to the current time, SHALL NOT
compute an age or elapsed duration for `pending_entry_recovery` or
`pending_close_recovery`, and SHALL NOT withhold, skip, or alter an ABI query
or command on the basis of how long a marker has been pending. Whether an
entry-recovery attempt can resolve depends entirely on ABI's response —
specifically, whether it is one of the four positive `recovery_state`
values below. Whether a close-recovery attempt can resolve depends entirely
on whether the re-issued close command converges to `terminal_closed`. In
neither case does elapsed time play any role.

#### Scenario: Every attempt queries or acts against ABI regardless of how long the marker has been pending
- **WHEN** the resolver attempts to resolve an instance whose
  `pending_entry_recovery` or `pending_close_recovery` has persisted across
  many prior unresolved attempts
- **THEN** the resolver acts exactly the same way it would for a marker set
  moments ago — no different code path, no skipped query or command, no
  escalation to a different outcome based on elapsed time

#### Scenario: Age never permits stale CREATE resurrection
- **WHEN** an uncertain APPLY is arbitrarily old
- **THEN** Runtime never resends its original CREATE or reconstructs its old desired entry
- **AND** only explicit current ABI evidence controls recovery

#### Scenario: Aged-out ABI evidence produces no Runtime fallback
- **WHEN** ABI declines to emit the fifth state and returns its safe error because the
  binding is outside ABI's trustworthy evidence window
- **THEN** Runtime leaves `pending_entry_recovery` and `current_trade_cycle` unchanged
- **AND** sends no corrective CANCEL and performs no local age inference

### Requirement: A transport failure, availability failure, inconclusive-evidence response, or unknown-binding response all change nothing
When the ABI query does not return one of the five typed recovery states — because of a
timeout, transport/network failure, protocol error, ABI availability failure,
inconclusive evidence, or `422 unknown_trade_cycle_binding` — the resolver SHALL modify
nothing and retry on a later tick. `entry_order_not_found` is not part of this failure
class after the paired contract change; it follows only the explicit uncertain-APPLY
neutralization row above.

#### Scenario: A failed or inconclusive query leaves the marker untouched
- **WHEN** the recovery client raises or returns no typed recovery state
- **THEN** Runtime changes no durable state and issues no corrective command

#### Scenario: Unknown trade-cycle binding is not treated as absence
- **WHEN** ABI returns `422 unknown_trade_cycle_binding`
- **THEN** Runtime does not treat it as `entry_order_not_found`,
  `terminal_without_fill`, or `EntryPackageAbsent`
- **AND** leaves the marker untouched

#### Scenario: Only ABI's typed fifth state enters the new neutralization row
- **WHEN** the strict client returns `entry_order_not_found`
- **THEN** Runtime may issue corrective CANCEL only if the marker represents uncertain
  APPLY
- **AND** does not infer that state from any exception or HTTP error

### Requirement: The resolver never initiates Engine evaluation or position management
The resolver SHALL NOT call `StrategyUseCaseRouter`, Strategy Engine,
`EntryReconciliationOrchestrator`, or `PositionManagementOrchestrator`, even
when an entry-recovery resolution discovers a fill. For close recovery, the
resolver's only permitted mutation is the single re-issued `close_position`
call defined above — it SHALL NOT invoke `PositionManagementOrchestrator`,
`decide_position_management`, or any protection-related operation as part of
resolving `pending_close_recovery`.

#### Scenario: A discovered fill does not trigger immediate management
- **WHEN** an entry-recovery resolution attempt discovers `position_open`
- **THEN** the resolver saves the resolved state and returns
- **AND** does not call the use-case router, Strategy Engine, or
  `PositionManagementOrchestrator` as part of this attempt
- **AND** the next committed bar's ordinary open-position resolution and
  routing discover the open position and proceed through the normal
  position-management pipeline

#### Scenario: Close recovery calls only the execution port, never the orchestrator
- **WHEN** the resolver attempts to resolve a `pending_close_recovery` marker
- **THEN** it calls `PositionManagementExecutionPort.close_position`
  directly
- **AND** does not call `PositionManagementOrchestrator.execute` or
  `decide_position_management`

### Requirement: The background worker follows the existing intake-worker lifecycle shape
Strategy Runtime SHALL provide a background worker that drives resolution
attempts on a fixed, bounded polling interval, using the same lifecycle shape
as `CommittedBarIntakeWorker`: an explicit state machine, `start()`/
`stop_once()` with `join()`, and per-attempt exception isolation that logs
and continues rather than stopping the loop. No adaptive or exponential
backoff is required for V1; a generic retry/backoff framework is out of
scope for this component. The same single worker, thread, and interval drive
both entry-recovery and close-recovery resolution — no second scheduler or
thread is introduced for close recovery.

#### Scenario: One tick attempts every currently pending instance, for both marker kinds
- **WHEN** the worker's interval elapses
- **THEN** it enumerates pending instances via
  `list_ids_with_pending_entry_recovery()` and
  `list_ids_with_pending_close_recovery()` and attempts resolution for each
- **AND** a failure resolving one instance does not prevent attempting the
  others in the same tick, regardless of marker kind

#### Scenario: One tick attempts each id at most once, even if returned by both enumerations
- **WHEN** the two enumerations for one tick contain the same
  `strategy_instance_id` (defensive: the domain model already forbids both
  markers being set on one instance, so this should not occur in practice)
- **THEN** the worker calls `resolver.attempt(...)` for that id exactly once
  in that tick, not once per enumeration it appeared in

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
  `pending_entry_recovery` and `pending_close_recovery` markers
  `JsonlStrategyInstanceRuntimeStateRepository`'s existing startup replay
  already restored
- **AND** process readiness does not wait for any outstanding marker of
  either kind to resolve

#### Scenario: Graceful shutdown joins an in-flight attempt before closing ABI clients
- **WHEN** the process shuts down
- **THEN** the worker stops scheduling new attempts and joins any in-flight
  bounded attempt, of either marker kind
- **AND** this completes before the ABI HTTP client used by the resolver is
  closed

### Requirement: Pending close recovery journals a confirmed closure after the save
When a pending-close attempt receives a confirmation carrying a closure, the resolver SHALL apply and save the state through the existing confirmation path, and only then journal `trade_cycle_closed` with `bar_open_time_ms: null`. A confirmation without a closure SHALL clear state as today and write no record.

#### Scenario: Stop filled while the close was pending
- **WHEN** `pending_close_recovery` is set and ABI answers the close with a `stop_loss` closure
- **THEN** the cycle and the marker are cleared, and one `trade_cycle_closed` record with reason `stop_loss` follows the save

### Requirement: An uncertain Apply resolved as position_open journals the Open Trade transition after the save
When an uncertain Apply resolves as `position_open` and the reconstructed, frozen state was durably saved, the resolver SHALL write one `trade_cycle_opened` record with `bar_open_time_ms: null` and the recovery response's `first_fill_at_ms`, `average_entry_price`, `entry_order_link_id` and `entry_order_id`. An uncertain removal resolved as `position_open` does not freeze the cycle and SHALL write no record; the bar path writes it when it freezes the cycle.

#### Scenario: Uncertain Apply resolved as position_open
- **WHEN** the resolver reconstructs and freezes the cycle from a `position_open` response and the save succeeds
- **THEN** exactly one `trade_cycle_opened` record is written after the save with `bar_open_time_ms: null`

#### Scenario: Uncertain removal resolved as position_open
- **WHEN** the resolver clears `pending_entry_recovery` for a `position_open` response on an existing cycle
- **THEN** no `trade_cycle_opened` record is written by the resolver

### Requirement: An uncertain Apply resolves by the five ABI-reported states
When `pending_entry_recovery` is non-null and `current_trade_cycle` is null, the resolver
SHALL apply the following table.

#### Scenario: entry_order_live or position_open reconstructs the cycle
- **WHEN** ABI reports `entry_order_live` or `position_open`
- **THEN** the resolver builds `CurrentTradeCycle` for the pending trade-cycle identity
  from the response's applied package
- **AND** for `position_open` freezes the first-fill context from the response fill facts
- **AND** durably clears `pending_entry_recovery`

#### Scenario: terminal_without_fill or terminal_after_fill forgets the attempt
- **WHEN** ABI reports `terminal_without_fill` or `terminal_after_fill`
- **THEN** the resolver durably stores both `current_trade_cycle` and
  `pending_entry_recovery` as null
- **AND** does not resend CREATE or revive the old desired entry

#### Scenario: entry_order_not_found triggers one neutralizing CANCEL
- **WHEN** ABI reports `entry_order_not_found` for an uncertain APPLY
- **THEN** the resolver sends exactly one bounded corrective CANCEL for the same strategy
  instance and `pending_entry_recovery.trade_cycle_id`
- **AND** uses the existing entry-package request with `desired_entry:null`
- **AND** does not send CREATE, reconstruct desired entry, or clear the marker from the GET
  observation alone
- **AND** does not independently re-evaluate the evidence age that ABI already validated

#### Scenario: Exact EntryPackageAbsent completes neutralization
- **WHEN** that corrective CANCEL returns formal `EntryPackageAbsent` whose strategy
  instance and trade-cycle identity exactly match the pending marker
- **THEN** the resolver durably saves `current_trade_cycle:null` and
  `pending_entry_recovery:null` in the same attempt
- **AND** only a later genuine bar may calculate a fresh ordinary entry

#### Scenario: Any other neutralizing-CANCEL result changes nothing
- **WHEN** the corrective CANCEL fails, times out, returns a public/protocol error,
  returns `EntryPackageApplied`, returns mismatched absence, or any unrecognized result
- **THEN** Runtime changes neither `current_trade_cycle` nor `pending_entry_recovery`
- **AND** a later polling attempt starts again from a fresh recovery GET
- **AND** this includes ABI refusing `EntryPackageAbsent` because the evidence window
  expired between GET and corrective CANCEL

### Requirement: An uncertain removal resolves by the five ABI-reported states, with one existing corrective action
When `pending_entry_recovery` is non-null and `current_trade_cycle` holds the matching
cycle being removed, the existing uncertain-removal table SHALL remain unchanged for its
four original states. `entry_order_not_found` SHALL cause no corrective action and no
state change because the new neutralization row applies only to uncertain APPLY.

#### Scenario: terminal_without_fill or terminal_after_fill confirms the removal
- **WHEN** ABI reports either terminal state
- **THEN** the resolver durably saves `current_trade_cycle:null` and
  `pending_entry_recovery:null`

#### Scenario: position_open means removal lost the race to a fill
- **WHEN** ABI reports `position_open`
- **THEN** the resolver clears only `pending_entry_recovery` and leaves the current cycle
  unchanged for ordinary position management

#### Scenario: entry_order_live triggers the existing corrective action
- **WHEN** ABI reports `entry_order_live`
- **THEN** the resolver sends one bounded CANCEL for the pending trade-cycle identity and
  no other command

#### Scenario: Exact matching absent confirmation completes removal
- **WHEN** that corrective CANCEL returns exact formal `EntryPackageAbsent`
- **THEN** the resolver durably clears both current cycle and pending marker in the same
  attempt

#### Scenario: Any other removal-CANCEL result leaves state untouched
- **WHEN** the corrective CANCEL fails or does not return exact matching absence
- **THEN** Runtime modifies neither field and remains eligible for a later attempt

#### Scenario: entry_order_not_found does not change uncertain-removal behavior
- **WHEN** ABI reports `entry_order_not_found` while `current_trade_cycle` holds the
  matching cycle being removed
- **THEN** Runtime sends no corrective command and changes no state
- **AND** the marker remains eligible for a later fresh observation

### Requirement: An uncertain close resolves by re-issuing the close command through the canonical confirmation-application path
When `pending_close_recovery` is non-null, the resolver SHALL resolve it by
calling `PositionManagementExecutionPort.close_position` again with a
`ClosePositionCommand` for `pending_close_recovery.trade_cycle_id`, relying
on ABI's own pair-scoped `close_position` idempotency (a `terminal_closed`
record short-circuits with no exchange mutation; an in-progress or
not-yet-dispatched close re-derives every fact fresh and reuses its durable
deterministic `close_order_link_id` rather than dispatching a second market
order) rather than performing a read-only query of its own. On a returned
confirmation, the resolver SHALL apply it through the exact same
`apply_position_management_confirmation` helper (`position_management_execution`)
that `PositionManagementOrchestrator` calls for a synchronous close — the
resolver SHALL NOT implement a second, hand-rolled state transition for
clearing `current_trade_cycle`/`pending_close_recovery`. A synchronous close
and an asynchronous recovery close therefore apply the identical state
transition rule.

#### Scenario: A verified confirmation clears both fields in the same write, via the canonical helper
- **WHEN** the re-issued `close_position` call returns a matching
  `PositionClosedConfirmation`
- **THEN** the resolver passes it to `apply_position_management_confirmation`
  — the same helper `PositionManagementOrchestrator` uses — which clears
  `current_trade_cycle` and `pending_close_recovery` together in the
  returned state
- **AND** the resolver then durably saves that returned state; it does not
  construct the cleared state by its own `replace(...)` call

#### Scenario: An expected external execution failure leaves the marker untouched
- **WHEN** the re-issued `close_position` call raises a
  `PositionManagementExecutionError` (or any of its subtypes: transport
  failure, timeout, protocol error, or a documented public rejection)
  instead of returning a confirmation
- **THEN** the resolver durably changes nothing
- **AND** the instance remains eligible for another attempt on the next tick

#### Scenario: An unexpected exception propagates instead of being swallowed
- **WHEN** the re-issued `close_position` call raises any exception that is
  not a `PositionManagementExecutionError` — a programming error, not a
  documented external execution failure
- **THEN** the resolver does not catch it
- **AND** it propagates out of `attempt(...)` to the worker's own
  per-instance exception isolation and logging, exactly like any other
  unexpected exception during a tick

#### Scenario: A mismatched confirmation leaves the marker untouched rather than corrupting state
- **WHEN** `apply_position_management_confirmation` raises
  `PositionManagementExecutionInvariantError` for the re-issued call's
  confirmation
- **THEN** the resolver does not save any state
- **AND** `pending_close_recovery` and `current_trade_cycle` remain exactly
  as they were, eligible for a later attempt

