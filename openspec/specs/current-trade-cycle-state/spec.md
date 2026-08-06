# current-trade-cycle-state Specification

## Purpose

Define the minimal Runtime-owned current-cycle aggregate, its acknowledged
entry-package value, and Runtime-owned trade-cycle identity boundary without
pre-empting the deferred ABI fill contract.
## Requirements
### Requirement: Strategy-instance state owns at most one minimal current cycle
`StrategyInstanceRuntimeState` SHALL contain
`current_trade_cycle: CurrentTradeCycle | null`, where null means Runtime owns
no acknowledged current trade cycle.

#### Scenario: Represent no Runtime-owned acknowledged current cycle
- **WHEN** `current_trade_cycle` is null
- **THEN** Runtime state contains no acknowledged current-cycle identity or
  applied entry package
- **AND** Runtime makes no claim that an exchange order or real position is absent

#### Scenario: Nest one acknowledged current cycle
- **WHEN** `current_trade_cycle` is non-null
- **THEN** exactly one complete `CurrentTradeCycle` with one required
  `AppliedEntryPackage` is nested under that strategy instance
- **AND** the aggregate cannot contain a second concurrent current cycle

### Requirement: Current trade cycle has only the minimal I2 fields
`CurrentTradeCycle` SHALL contain exactly one non-empty `trade_cycle_id`, one
required `applied_entry_package: AppliedEntryPackage`, one nullable
`frozen_entry_context: FrozenExecutedEntryContext | null`, and one nullable
latest confirmed management protection:
`latest_confirmed_management_protection: DesiredProtection | null`. Null
means Runtime has not yet acknowledged any post-entry management change;
the initial protection remains available from
`frozen_entry_context.desired_entry` regardless. Runtime SHALL store only
this single latest confirmed value, never a history.

#### Scenario: Require an acknowledged applied package
- **WHEN** `CurrentTradeCycle` is constructed
- **THEN** `applied_entry_package` is a complete `AppliedEntryPackage`
- **AND** it cannot be null

#### Scenario: Reject an empty current cycle
- **WHEN** `applied_entry_package` is null or has the wrong type
- **THEN** cycle construction fails before the value can enter aggregate or
  repository state
- **AND** Runtime defines no recovery, compatibility, or transitional semantics
  for that invalid value

#### Scenario: Represent a cycle before any fill
- **WHEN** `frozen_entry_context` is null
- **THEN** the cycle still retains its `trade_cycle_id` and
  `applied_entry_package`
- **AND** Runtime makes no claim that any exchange fill has occurred

#### Scenario: Exclude deferred execution state
- **WHEN** a current cycle is modeled
- **THEN** it contains no phase, filled quantity, remaining quantity,
  average entry price, fill timestamp, or fill ledger anywhere on the
  cycle or on any non-null `frozen_entry_context`
- **AND** it contains no protection history, pending execution state,
  diagnostics, or full `PositionManagementRecipe` — only the single
  nullable latest confirmed management protection

#### Scenario: No management acknowledgement yet
- **WHEN** a current trade cycle has never had a management protection
  acknowledged
- **THEN** its latest confirmed management protection is null
- **AND** its initial protection is still readable from
  `frozen_entry_context.desired_entry`

#### Scenario: One replaceable acknowledged value
- **WHEN** a current trade cycle's latest confirmed management protection
  is set
- **THEN** it holds exactly one `DesiredProtection` value
- **AND** no prior acknowledged protection, pending change, or diagnostics
  value is retained alongside it

### Requirement: Applied entry package is one indivisible nested value
`AppliedEntryPackage` SHALL contain exactly `applied_desired_entry` and
`calculated_quantity`.

#### Scenario: Preserve one singular desired entry
- **WHEN** an applied package is constructed
- **THEN** it contains one complete `DesiredEntry` under `applied_desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as another field
- **AND** no separate long and short applied-entry objects exist

#### Scenario: Preserve confirmed quantity lexeme
- **WHEN** a valid confirmed quantity string is supplied
- **THEN** `calculated_quantity` is finite exact-decimal text
- **AND** the accepted lexeme is retained without binary floating-point conversion or textual normalization

#### Scenario: Reject invalid package fields
- **WHEN** applied desired entry has the wrong type or calculated quantity is not finite exact-decimal text
- **THEN** package construction fails before the value can enter repository state

#### Scenario: Keep wire and exchange details outside the package
- **WHEN** an applied package is stored
- **THEN** it contains no HTTP status, response envelope, exchange order payload, stop reference, take reference, fill fact, or execution phase

### Requirement: Trade-cycle identity is Runtime-owned and opaque
Every `CurrentTradeCycle` SHALL preserve one supplied non-empty opaque
`trade_cycle_id` without deriving or rewriting it.

#### Scenario: Preserve a valid cycle identity
- **WHEN** a cycle is constructed with a valid identity
- **THEN** the exact string is retained
- **AND** it is not derived from ticker, side, price, Strategy Engine output, ABI acknowledgement data, or an exchange identifier

#### Scenario: Reject an invalid cycle identity
- **WHEN** the identity is empty or not a string
- **THEN** cycle construction fails before repository save

#### Scenario: Keep cycle identity out of Strategy Engine
- **WHEN** Runtime owns a trade-cycle identity
- **THEN** I2 does not add it to any Strategy Engine request or response

### Requirement: Production-generated trade-cycle identities are unique
Runtime SHALL expose an injected `TradeCycleIdFactory` boundary and a
production implementation that generates a distinct opaque identity for every
new trade cycle.

#### Scenario: Generate identities for different cycles
- **WHEN** the production factory is invoked for two different new cycles
- **THEN** it returns two different non-empty identities
- **AND** neither value is user-authored, ABI-authored, or exchange-authored

#### Scenario: Preserve test injectability
- **WHEN** deterministic identity generation is needed in a test
- **THEN** application code can receive an injected test factory
- **AND** the production uniqueness requirement remains unchanged

#### Scenario: Generate no cycle identity during instance registration
- **WHEN** repository `get_or_create` creates initial strategy-instance state
- **THEN** no trade-cycle identity factory is invoked
- **AND** `current_trade_cycle` is null

#### Scenario: Introduce no second command identity
- **WHEN** the trade-cycle identity boundary is implemented
- **THEN** Runtime introduces no `command_id`, Engine `trade_id`, or duplicate cycle-correlation identifier

### Requirement: Minimal current-cycle state does not prove exchange state
The presence or absence of a Runtime-owned acknowledged current cycle SHALL NOT
be treated as authoritative proof of current exchange order or position
existence.

#### Scenario: Acknowledged current cycle is absent
- **WHEN** `current_trade_cycle` is null
- **THEN** Runtime owns no acknowledged current-cycle identity or applied
  package
- **AND** an ABI lookup remains authoritative for exchange position facts

#### Scenario: Acknowledged current cycle exists
- **WHEN** `current_trade_cycle` is non-null
- **THEN** Runtime owns its complete acknowledged entry package
- **AND** that state alone does not prove the package remains pending, has
  filled, or corresponds to a currently open exchange position
- **AND** an ABI lookup remains authoritative for current exchange position facts

### Requirement: Entry reconciliation changes current-cycle state only after matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change for entry
reconciliation only after a successful confirmation matches the expected
action, ownership identities, originating command, and source-state
preconditions.

#### Scenario: Create a cycle after successful apply
- **WHEN** `Apply` receives a matching `EntryAppliedConfirmation`
- **AND** source `current_trade_cycle` is null
- **THEN** Runtime creates `CurrentTradeCycle` only after that confirmation
- **AND** sets its `trade_cycle_id` to the acknowledged target identity
- **AND** stores one complete `AppliedEntryPackage` containing the acknowledged
  desired entry and calculated quantity

#### Scenario: Do not create a cycle before apply confirmation
- **WHEN** an `Apply` command is constructed
- **THEN** the source state's current-cycle value remains unchanged
- **AND** the caller-selected trade-cycle identity is not inserted into the
  aggregate merely because it was reserved or sent

#### Scenario: Replace the complete package after successful replace
- **WHEN** `Replace` receives a matching `EntryAppliedConfirmation` for the
  acknowledged current cycle
- **THEN** Runtime retains the existing `trade_cycle_id`
- **AND** atomically replaces the entire `AppliedEntryPackage` with the
  acknowledged desired entry and calculated quantity
- **AND** does not create a new trade cycle

#### Scenario: Clear the complete cycle after successful cancel
- **WHEN** `Cancel` receives a matching `EntryAbsentConfirmation` for the
  acknowledged current cycle
- **THEN** Runtime sets `current_trade_cycle` to null
- **AND** does not construct or retain a `CurrentTradeCycle` with a null applied
  package

#### Scenario: Every valid transition preserves the non-empty-cycle invariant
- **WHEN** `Apply`, `Replace`, or `Cancel` completes successfully
- **THEN** resulting state contains either null `current_trade_cycle` or one
  complete cycle with one required `AppliedEntryPackage`
- **AND** no valid transition produces an empty current cycle

#### Scenario: Preserve state after contradictory formal success
- **WHEN** a formally successful confirmation contradicts the expected
  action, ownership identities, sent desired entry, or source-state
  preconditions
- **THEN** confirmation application raises
  `EntryReconciliationInvariantError`
- **AND** the input `StrategyInstanceRuntimeState` remains unmodified and
  domain-value-equivalent to its pre-call snapshot
- **AND** no empty, partial, pending, or provisional current cycle is stored

### Requirement: Frozen executed entry context is the minimal first-fill freeze
`FrozenExecutedEntryContext` SHALL contain exactly `desired_entry:
DesiredEntry`, a strictly positive integer `first_fill_at_ms` (type checked,
`> 0`), and a non-negative integer `entry_bar_open_time_ms` (type checked,
`>= 0`) where `entry_bar_open_time_ms <= first_fill_at_ms`.

#### Scenario: Preserve one singular desired entry
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains one complete `DesiredEntry` under `desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as
  another field outside `applied_entry_package`/`frozen_entry_context`

#### Scenario: Reject invalid context fields
- **WHEN** `desired_entry` has the wrong type, `first_fill_at_ms` is not a
  strictly positive integer, `entry_bar_open_time_ms` is not a
  non-negative integer, or `entry_bar_open_time_ms > first_fill_at_ms`
- **THEN** context construction fails before the value can enter aggregate
  or repository state

#### Scenario: Keep price, quantity, and phase out of the frozen context
- **WHEN** a frozen executed entry context is constructed
- **THEN** it contains no average execution price, filled quantity,
  remaining quantity, fill ledger entry, execution phase, or any
  execution-lifecycle state
- **AND** it contains exactly the three required fields: `desired_entry`,
  `first_fill_at_ms`, `entry_bar_open_time_ms`

### Requirement: The current trade cycle gains its frozen executed entry context only through the first-fill transition
`CurrentTradeCycle.frozen_entry_context` SHALL remain null until the
Runtime-owned first-fill transition (defined by the `first-fill-transition`
capability) successfully applies a fill for that cycle, and once set SHALL
retain the exact `FrozenExecutedEntryContext` produced by that transition.

#### Scenario: No frozen context before any recorded fill
- **WHEN** no fill has ever been successfully applied for a trade cycle
- **THEN** its `frozen_entry_context` remains null
- **AND** Runtime makes no claim about whether ABI or the exchange has
  filled any order for that cycle

#### Scenario: One frozen context after the first recorded fill
- **WHEN** the first-fill transition has successfully applied a fill for a
  trade cycle
- **THEN** that cycle's `frozen_entry_context` is the one
  `FrozenExecutedEntryContext` the transition produced
- **AND** no separate, second, or partially-populated frozen context exists
  alongside it

### Requirement: Runtime-issued position-management execution changes current-cycle state only after a matching confirmation
`StrategyInstanceRuntimeState.current_trade_cycle` SHALL change due to
Runtime-issued position-management execution only after a confirmation from
`PositionManagementExecutionPort` matches the originating decision's
ownership identities, action type, and (for protection) confirmed value.
This requirement governs only Runtime-issued `ApplyProtection` /
`ClosePosition` execution; it neither defines nor precludes a future
external-close lifecycle (e.g. Runtime reacting to ABI reporting
`position_open=false` after an exchange-side close).

#### Scenario: Update confirmed protection after a matching apply confirmation
- **WHEN** `ApplyProtection` receives a matching `ProtectionAppliedConfirmation`
- **THEN** Runtime replaces
  `current_trade_cycle.latest_confirmed_management_protection` with the
  confirmed value
- **AND** every other field of that cycle is unchanged

#### Scenario: Clear the current cycle after a matching close confirmation
- **WHEN** `ClosePosition` receives a matching `PositionClosedConfirmation`
- **THEN** Runtime sets `current_trade_cycle` to null

#### Scenario: Preserve state after a contradictory formal success
- **WHEN** a formally successful confirmation contradicts the expected
  action, ownership identities, sent command, or the current cycle's
  `trade_cycle_id`
- **THEN** confirmation application raises
  `PositionManagementExecutionInvariantError`
- **AND** the input `StrategyInstanceRuntimeState` remains unmodified and
  domain-value-equivalent to its pre-call snapshot

