## Context

The implemented semantic path stops after returning a typed live-entry or
open-trade projection. On the live-entry branch, Runtime has a singular
`DesiredEntry | null` and a minimal immutable
`StrategyInstanceRuntimeState`.

I1 established the ABI client. I2 established minimal current-cycle state,
trade-cycle identity, repository operations, and keyed coordination. I3
supplies only deterministic reconciliation components for the next seam. I4
will order repository access, cycle-ID reservation, adaptation to the existing
ABI client, the real call, adaptation of a successful client result, state
application, save, and failure reporting.

## Goals / Non-Goals

**Goals:**

- Compare only the new and acknowledged singular desired entries by exact
  complete domain value.
- Produce exactly one of the closed payload-bearing variants `NoOp`, `Apply`,
  `Replace`, or `Cancel`.
- Return no command only for a valid `NoOp`; fail explicitly when a required
  command cannot be constructed.
- Build a transport-free I3 command without invoking an outbound port.
- Apply only an I3 successful confirmation and fail explicitly if that
  confirmation contradicts the expected operation.
- Create complete new immutable state only after a valid confirmation.
- Make `current_trade_cycle = null` the only representation of no Runtime-owned
  acknowledged cycle and require a complete applied package whenever a cycle
  exists.
- Make dependency isolation, exact failure behavior, and value preservation
  testable without constraining Python object identity.

**Non-Goals:**

- No `EntryReconciliationOrchestrator`, ABI-client call, HTTP call, repository
  `get`/`save`, keyed mutex, production composition, handoff wiring, Engine
  flow, routing, or ABI position lookup.
- No I3 handling of public ABI errors, timeout, network failure, protocol
  failure, or an absent successful result.
- No trade-cycle ID generation or decision about when I4 reserves an ID.
- Risk multiplier handling is outside I3. I3 reconciliation and state-transition components are completely unaware of it.
- No quantity calculation, bankroll, leverage, or exchange mechanics.
- No fallback command, immediate retry, automatic cancel, or local state
  mutation after command construction failure.
- No recovery, compatibility, migration state, or transitional interpretation
  for `CurrentTradeCycle(applied_entry_package=null)`; construction is invalid.
- No fill webhook, phase, `FrozenExecutedEntryContext`, position-management
  state, durable persistence, CAS, pending action, idempotency, or restart
  recovery.
- No change to the existing ABI request or response contract, Runtime ABI
  client, or ABI Executor repository.

## Decisions

### Keep four small pure responsibilities

The implementation will keep these responsibilities independently callable:

```text
DesiredEntry value equivalence
        ↓
entry reconciliation decision
        ↓
I3 command construction
        ↓
successful confirmation application
```

Suggested transport-free types and signatures are:

```text
NoOp

Apply
└── desired_entry: DesiredEntry

Replace
├── trade_cycle_id: str
└── desired_entry: DesiredEntry

Cancel
└── trade_cycle_id: str

EntryReconciliationDecision =
    NoOp | Apply | Replace | Cancel

EntryReconciliationCommand
├── strategy_instance_id: str
├── trade_cycle_id: str
├── ticker: str
└── desired_entry: DesiredEntry | null

EntryAppliedConfirmation
├── strategy_instance_id: str
├── trade_cycle_id: str
├── applied_desired_entry: DesiredEntry
└── calculated_quantity: str

EntryAbsentConfirmation
├── strategy_instance_id: str
└── trade_cycle_id: str

SuccessfulEntryConfirmation =
    EntryAppliedConfirmation | EntryAbsentConfirmation

EntryReconciliationInvariantError

decide_entry_reconciliation(
    new_desired_entry: DesiredEntry | null,
    current_trade_cycle: CurrentTradeCycle | null,
) -> EntryReconciliationDecision

build_entry_reconciliation_command(
    state: StrategyInstanceRuntimeState,
    decision: EntryReconciliationDecision,
    apply_trade_cycle_id: str | null = null,
) -> EntryReconciliationCommand | null

apply_success_confirmation(
    state: StrategyInstanceRuntimeState,
    decision: Apply | Replace | Cancel,
    sent_command: EntryReconciliationCommand,
    confirmation: SuccessfulEntryConfirmation,
) -> StrategyInstanceRuntimeState
```

The builder's nullable return has exactly one meaning: valid `NoOp`. Every
incoherent command-bearing decision raises
`EntryReconciliationInvariantError`. The applier has no result wrapper, null
input, public-error input, or failure taxonomy. A contradictory formal success
raises the same exception.

I4 owns both adaptations at the actual call boundary: from
`EntryReconciliationCommand` to the already-existing client request and from a
successful client result to `SuccessfulEntryConfirmation`. I3 neither imports
nor redefines the ABI transport models.

**Rationale:** These signatures distinguish “no change is required” from “a
change is required but cannot be represented safely,” eliminate duplicate
builder inputs, and keep transport behavior outside the state-transition
boundary.

**Alternative considered:** Return null for any builder failure or pass the
client's complete result union into the applier. That conflates successful
`NoOp` with processing failure and makes a pure success transition interpret
I4 transport outcomes.

### Make every current cycle an acknowledged non-empty cycle

The aggregate has exactly two valid lifecycle shapes:

```text
StrategyInstanceRuntimeState
└── current_trade_cycle = null

StrategyInstanceRuntimeState
└── current_trade_cycle = CurrentTradeCycle(
        trade_cycle_id = ...,
        applied_entry_package = AppliedEntryPackage(...),
    )
```

`current_trade_cycle = null` means Runtime owns no acknowledged current trade
cycle. If a `CurrentTradeCycle` exists, its `applied_entry_package` is required
and non-null:

```text
CurrentTradeCycle
├── trade_cycle_id
└── applied_entry_package: AppliedEntryPackage
```

The model constructor rejects null package input. Reconciliation, command
construction, and confirmation application never interpret, repair, or recover
an empty cycle because that value cannot validly enter aggregate state.

**Rationale:** A cycle is created only by an applied confirmation and is
removed completely by an absent confirmation. There is no lifecycle event
whose correct result is an identity-bearing cycle without an acknowledged
package.

**Alternative considered:** Preserve the I2 nullable package and teach
reconciliation to treat an empty cycle like no cycle. That adds a third state
with no valid producer and forces recovery semantics into otherwise pure
lifecycle rules.

### Compare complete canonical DesiredEntry values

When `current_trade_cycle` exists, the currently applied value is read only
from:

```text
state.current_trade_cycle
    .applied_entry_package
    .applied_desired_entry
```

The compatibility property `desired_entry_frozen` is not persisted state and is
not an input. Two desired entries are equivalent only when all six fields are
equal:

```text
side
source_plan_bar_open_time_ms
planned_entry_price
initial_stop_price
initial_take_price
locked_exit_profile
```

`DesiredEntry` already validates and normalizes decimal text during
construction. Reconciliation uses ordinary immutable domain-value equality and
adds no tolerance, partial comparison, side arbitration, or normalization.
`current_trade_cycle` is supplied only so reconciliation can extract the
acknowledged desired entry and carry the existing `trade_cycle_id` in
`Replace` or `Cancel`. Cycle identity never affects which decision is selected.

| New desired entry | Acknowledged applied package | Decision |
|---|---|---|
| null | absent | `NoOp()` |
| `X` | absent | `Apply(desired_entry=X)` |
| `X` | contains equivalent `X` | `NoOp()` |
| `Y` | contains non-equivalent `X` in cycle `C` | `Replace(trade_cycle_id=C, desired_entry=Y)` |
| null | present in cycle `C` | `Cancel(trade_cycle_id=C)` |

**Rationale:** The Engine output is complete desired state, while only the
acknowledged applied package is authoritative for comparison.

### Build a command or raise; never substitute another action

The builder behavior is:

| Decision | `apply_trade_cycle_id` | Result |
|---|---|---|
| `NoOp` | must be null | null, successful no-command outcome |
| `Apply(desired_entry)` | required non-empty new ID | command with the decision desired entry and supplied new ID |
| `Replace(cycle_id, desired_entry)` | must be null | command with the decision desired entry and cycle ID |
| `Cancel(cycle_id)` | must be null | command with `desired_entry: null` and the decision cycle ID |

Every command copies `state.strategy_instance_id` and
`state.registered_spec_snapshot.instrument` as ticker.

`Replace` and `Cancel` already carry the acknowledged current cycle ID selected
by reconciliation. `Apply` carries its desired entry but cannot carry a cycle
ID because no acknowledged cycle exists yet; I4 supplies
`apply_trade_cycle_id` after reserving it. I3 neither invokes
`TradeCycleIdFactory` nor inserts that ID into state before confirmation.

The builder validates only variant-specific invariants and coherence with the
provided state: `Apply` requires a new ID and null `current_trade_cycle`;
`Replace` and `Cancel` require the carried ID to equal the current acknowledged
cycle; `NoOp`, `Replace`, and `Cancel` reject a supplied apply-only ID. It does
not repeat reconciliation or receive a second desired entry or generic target
cycle ID.

If any `Apply`, `Replace`, or `Cancel` invariant is unsatisfied, the builder
raises `EntryReconciliationInvariantError`. It returns neither null nor a
fallback command:

```text
failed Replace ≠ NoOp
failed Replace ≠ Cancel
failed Cancel ≠ NoOp
```

I4 must treat this as unsuccessful closed-bar processing: do not call the
client, do not save new state, record/report the error, and perform no immediate
retry. A later committed bar follows the ordinary pipeline and may derive the
same action again. I3 exposes the error but implements none of that
orchestration.

**Rationale:** A missing command for a required change is operational failure,
not proof that no change is needed. Substituting another action would be an
unapproved exchange action.

### Preserve DesiredEntry and exact quantity without transport mapping

The I3 command carries the canonical domain `DesiredEntry` unchanged. The
applied confirmation also carries a canonical domain `DesiredEntry`, already
adapted by I4 before the applier is called. I3 performs no wire mapping and
never uses binary floating point.

`EntryAppliedConfirmation.calculated_quantity` and
`AppliedEntryPackage.calculated_quantity` preserve the accepted finite
exact-decimal text without binary conversion or textual normalization.

**Rationale:** The I3 boundary should express only domain command intent and
the facts needed for state transition. Client-specific wire conversion belongs
at the I4 call boundary.

### Apply only a successful confirmation

`NoOp` produces no command and never invokes the applier. For the other
actions, the closed transition table is:

| Decision variant | Required confirmation | Successful state |
|---|---|---|
| `Apply` | matching `EntryAppliedConfirmation` | create complete acknowledged cycle |
| `Replace` | matching `EntryAppliedConfirmation` | retain decision cycle ID and replace package |
| `Cancel` | matching `EntryAbsentConfirmation` | set `current_trade_cycle = null` |

For `Apply`, source `current_trade_cycle` is null. Only after a matching
confirmation does Runtime construct:

```text
CurrentTradeCycle(
    trade_cycle_id = confirmation.trade_cycle_id,
    applied_entry_package = AppliedEntryPackage(
        applied_desired_entry = confirmation.applied_desired_entry,
        calculated_quantity = confirmation.calculated_quantity,
    ),
)
```

For `Replace`, source state has an acknowledged package. The decision, sent
command, and confirmation target the same current cycle, and command and
confirmation desired entries equal the decision desired entry. The applier
retains the decision cycle ID and atomically replaces the complete
`AppliedEntryPackage`.

For `Cancel`, source state has an acknowledged package, and the decision,
command, and confirmation target the same current cycle. The confirmation is
`EntryAbsentConfirmation`. The sent command must contain
`desired_entry = null`; a present desired entry is an invariant violation even
if an absent confirmation was supplied. The complete `current_trade_cycle`
becomes null.

Wrong confirmation variant, strategy-instance mismatch, trade-cycle mismatch,
applied-entry mismatch, invalid confirmation quantity, or incoherent source
state raises `EntryReconciliationInvariantError`. Immutable source objects are
not modified, and no partial replacement is observable.

State preservation is a domain-value guarantee, not a Python allocation
guarantee. Tests snapshot the input aggregate and assert value equality after
`NoOp` or invariant failure. They do not require `result is state`, preserve
nested object identity, or constrain an implementation from creating an
equivalent immutable copy. When an invariant exception is raised, no state
value is returned; the input value remains unmodified and no transition is
available for repository save.

**Rationale:** The applier answers one question only: whether a successful I3
confirmation proves the expected state transition.

### Leave all non-success client outcomes to I4

These are not I3 confirmation-applier inputs:

```text
public client error
timeout
network failure
protocol decoding failure
missing result
```

Future I4 orchestration will preserve current state and skip
`apply_success_confirmation` whenever the client interaction does not yield a
successful result that can be adapted to one I3 confirmation. I3 defines no
unconfirmed-outcome model, retry, fallback, recovery, or transport-error
mapping.

**Rationale:** With no successful confirmation there is nothing for a
success-to-state function to apply.

### Keep dependency direction pure

Pure I3 components may depend on:

```text
runtime.recipes.entry
runtime.state.models
shared value utilities
```

They must not import ABI request/response models, an ABI port or HTTP adapter,
repository, keyed mutex, Engine, open-position lookup, handoff, orchestrators,
bootstrap, or infrastructure.

## Trade-offs

- [The HTTP client already validates ownership identifiers] → Revalidate them
  at the state boundary because pure tests and future non-HTTP adapters can
  construct confirmations directly.
- [A confirmation can be constructed with an invalid quantity] → Validate it
  and raise `EntryReconciliationInvariantError` before constructing new state.
- [Command invariant failure repeats on later bars until its cause is fixed] →
  Preserve state, emit an unsuccessful processing outcome in I4, avoid
  fallback/immediate retry, and allow the ordinary next-bar pipeline to try
  again.
- [A timeout may follow real external application] → I4 preserves prior state
  and does not invoke the I3 applier; pending actions, idempotency, and recovery
  remain deferred.
- [The prior I2 constructor accepted an empty cycle] → Tighten the model
  constructor and focused tests so null package input is invalid; introduce no
  recovery branch because the repository is in-memory and no durable migration
  is part of I3.
- [A future adapter could accidentally leak transport concerns inward] → Keep
  architecture tests that prohibit imports from ABI models, ports, and
  adapters in every pure I3 module.

## Migration Plan

1. Make `CurrentTradeCycle.applied_entry_package` required and update aggregate,
   repository-model, and state-model tests to reject null package construction.
2. Ensure `AppliedEntryPackage` contains exactly the acknowledged desired entry
   and calculated quantity.
3. Add the pure decision variants, exact equivalence, I3 command and
   confirmation models, and the single invariant exception.
4. Add pure command construction and exhaustive decision/builder tests.
5. Add the success-only confirmation applier and exhaustive transition tests.
6. Add architecture tests proving that existing ABI-client and orchestration
   layers are not imported or changed.
7. Leave all components unconnected until a separately approved I4 change
   supplies adaptation, invocation, non-success handling, persistence, and
   production composition.

Rollback restores the prior nullable current-cycle package model and removes
the unconnected pure I3 components. It requires no client-contract rollback
because I3 does not change that contract.

## Open Questions

None for I3 semantics. I4 retains client adaptation, orchestration, error
reporting, locking, persistence, and production-composition decisions.
