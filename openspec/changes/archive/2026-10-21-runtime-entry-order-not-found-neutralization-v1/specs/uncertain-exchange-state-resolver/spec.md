## MODIFIED Requirements

### Requirement: One attempt is a single bounded read, under the shared keyed mutex
Each resolution attempt for one `strategy_instance_id` SHALL acquire the shared
`StrategyInstanceKeyedMutexRegistry` lock for its full duration and SHALL perform at most
one bounded ABI recovery-state query plus at most one bounded corrective CANCEL. The
corrective CANCEL is allowed only for one of two explicit rows: uncertain removal plus
`entry_order_live`, or uncertain APPLY plus `entry_order_not_found`.

#### Scenario: Attempt acquires the same registry bar processing uses
- **WHEN** the resolver attempts one pending instance
- **THEN** it holds the shared keyed mutex for the duration of query, any eligible
  corrective CANCEL, and the resulting state save
- **AND** committed-bar and first-fill processing for that instance cannot interleave

#### Scenario: A resolved instance is invisible to a concurrent attempt
- **WHEN** the lock is acquired after another caller already cleared the marker
- **THEN** the attempt returns without querying ABI or issuing CANCEL

#### Scenario: Different instances resolve independently
- **WHEN** two different instances have pending markers
- **THEN** their resolution attempts do not block each other

#### Scenario: No attempt sends more than one corrective command
- **WHEN** either eligible corrective row is observed
- **THEN** the attempt sends at most one CANCEL and never sends CREATE or amend

### Requirement: Resolution applies no wall-clock gate of any kind
The resolver SHALL NOT compare a marker timestamp to current time, compute marker age, or
alter recovery behavior based on elapsed time. Resolution depends only on the current ABI
response, including the fifth `entry_order_not_found` observation, and the formal result
of any eligible corrective CANCEL. ABI alone decides whether its ambiguous-CREATE
order/execution evidence is complete and still inside the documented retention window;
Runtime SHALL NOT duplicate, widen, or bypass that gate.

#### Scenario: Every attempt queries ABI regardless of marker age
- **WHEN** a marker has survived any number of prior attempts
- **THEN** the resolver performs the same bounded query with no age threshold

#### Scenario: Age never permits stale CREATE resurrection
- **WHEN** an uncertain APPLY is arbitrarily old
- **THEN** Runtime never resends its original CREATE or reconstructs its old desired entry
- **AND** only explicit current ABI evidence controls recovery

#### Scenario: Aged-out ABI evidence produces no Runtime fallback
- **WHEN** ABI declines to emit the fifth state and returns its safe error because the
  binding is outside ABI's trustworthy evidence window
- **THEN** Runtime leaves `pending_entry_recovery` and `current_trade_cycle` unchanged
- **AND** sends no corrective CANCEL and performs no local age inference

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

## RENAMED Requirements

- FROM: `### Requirement: An uncertain Apply resolves by the four ABI-reported states`
- TO: `### Requirement: An uncertain Apply resolves by the five ABI-reported states`
- FROM: `### Requirement: An uncertain removal resolves by the four ABI-reported states, with one corrective action`
- TO: `### Requirement: An uncertain removal resolves by the five ABI-reported states, with one existing corrective action`
