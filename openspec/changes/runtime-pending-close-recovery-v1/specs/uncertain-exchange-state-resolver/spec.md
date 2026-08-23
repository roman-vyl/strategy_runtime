## MODIFIED Requirements

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

### Requirement: An uncertain close resolves by re-issuing the close command
When `pending_close_recovery` is non-null, the resolver SHALL resolve it by
calling `PositionManagementExecutionPort.close_position` again with a
`ClosePositionCommand` for `pending_close_recovery.trade_cycle_id`, relying
on ABI's own pair-scoped `close_position` idempotency (a `terminal_closed`
record short-circuits with no exchange mutation; an in-progress or
not-yet-dispatched close re-derives every fact fresh and reuses its durable
deterministic `close_order_link_id` rather than dispatching a second market
order) rather than performing a read-only query of its own.

#### Scenario: A verified confirmation clears both fields in the same write
- **WHEN** the re-issued `close_position` call returns a matching
  `PositionClosedConfirmation`
- **THEN** the resolver applies it through the same
  `current-trade-cycle-state` confirmation-application rules
  `PositionManagementOrchestrator` uses, clearing `current_trade_cycle` and
  `pending_close_recovery` together in one durable save

#### Scenario: A repeated failure or inconclusive re-issue leaves the marker untouched
- **WHEN** the re-issued `close_position` call raises (transport, timeout, or
  any other exception) instead of returning a matching confirmation
- **THEN** the resolver durably changes nothing
- **AND** the instance remains eligible for another attempt on the next tick

#### Scenario: A mismatched confirmation leaves the marker untouched rather than corrupting state
- **WHEN** the re-issued call returns a confirmation that fails the
  `current-trade-cycle-state` matching rules
- **THEN** the resolver does not apply it
- **AND** `pending_close_recovery` and `current_trade_cycle` remain exactly
  as they were, eligible for a later attempt

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
