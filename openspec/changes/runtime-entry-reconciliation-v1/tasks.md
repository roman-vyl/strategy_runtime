## 1. Correct the Current-Cycle Model

- [ ] 1.1 Make `AppliedEntryPackage` contain exactly
  `applied_desired_entry` and `calculated_quantity`, preserving both as
  validated domain values.
- [ ] 1.2 Make `CurrentTradeCycle.applied_entry_package` a required
  `AppliedEntryPackage` and reject null or wrong-type package input at model
  construction.
- [ ] 1.3 Remove all valid-state fixtures and helper branches that construct or
  interpret an empty current cycle; add no recovery or compatibility path for
  it.
- [ ] 1.4 Update state-model and repository-model tests for the complete package
  shape and non-empty-cycle invariant.

## 2. Pure Reconciliation Models and Equivalence

- [ ] 2.1 Add the closed immutable decision union
  `NoOp | Apply | Replace | Cancel`, with desired-entry payload on `Apply`,
  cycle-ID and desired-entry payload on `Replace`, cycle-ID payload on `Cancel`,
  and no payload on `NoOp`.
- [ ] 2.2 Add a helper that returns null only when `current_trade_cycle` is null
  and otherwise extracts the acknowledged desired entry through the required
  `current_trade_cycle.applied_entry_package.applied_desired_entry`.
- [ ] 2.3 Implement exact complete `DesiredEntry` value equivalence across
  side, source bar, all three prices, and locked exit profile without tolerance
  or extra normalization.
- [ ] 2.4 Implement the complete five-row decision table and populate every
  decision payload from the same new desired entry and current cycle used to
  select the variant.
- [ ] 2.5 Keep cycle identity and compatibility property
  `desired_entry_frozen` outside the equivalence inputs.

## 3. Pure I3 Command and Confirmation Models

- [ ] 3.1 Add `EntryReconciliationCommand` with exactly
  `strategy_instance_id`, `trade_cycle_id`, `ticker`, and
  `desired_entry: DesiredEntry | null`.
- [ ] 3.2 Add `EntryAppliedConfirmation` with exactly strategy-instance and
  cycle identities, canonical `applied_desired_entry`, and finite exact-decimal
  `calculated_quantity`.
- [ ] 3.3 Add `EntryAbsentConfirmation` with exactly strategy-instance and
  cycle identities and expose the closed
  `SuccessfulEntryConfirmation` union.
- [ ] 3.4 Keep client request/response DTO construction, wire conversion,
  response decoding, and client invocation outside every I3 component.
- [ ] 3.5 Test exact model shapes, canonical desired-entry preservation,
  quantity validation and lexeme preservation, and rejection of wrong field
  types.

## 4. Pure Command Construction

- [ ] 4.1 Add one shared `EntryReconciliationInvariantError` for every
  contradictory command-builder or successful-confirmation input, with no
  public failure-code enum.
- [ ] 4.2 Implement a pure builder accepting only aggregate state, one
  payload-bearing decision, and optional `apply_trade_cycle_id`, returning null
  only for `NoOp`.
- [ ] 4.3 For `Apply`, require null source `current_trade_cycle` plus
  `apply_trade_cycle_id`, and carry the decision desired entry,
  strategy-instance identity, registered instrument as ticker, and supplied
  cycle identity.
- [ ] 4.4 For `Replace`, use only the decision desired entry and existing cycle
  ID; for `Cancel`, use only the decision cycle ID and `desired_entry: null`;
  both prohibit `apply_trade_cycle_id`.
- [ ] 4.5 Validate variant-specific source-state and apply-ID invariants without
  accepting a duplicate new desired entry or generic target-cycle input and
  without recomputing reconciliation.
- [ ] 4.6 Raise `EntryReconciliationInvariantError` for missing apply ID, an
  apply-only ID supplied to another variant, a stale replace/cancel cycle ID,
  or another variant/source-state contradiction.
- [ ] 4.7 Prohibit fallback cancel/apply/replace commands, conversion of builder
  failure to `NoOp`, immediate retry, pending/suppression state, identity
  generation, state mutation, and client invocation so the next closed bar
  remains on the ordinary pipeline.
- [ ] 4.8 Test all valid builder outcomes, payload preservation, apply-only ID
  rules, stale decision detection, and every invariant failure, asserting that
  command absence means only `NoOp`.

## 5. Pure Successful-Confirmation State Application

- [ ] 5.1 Reuse the single `EntryReconciliationInvariantError`; do not add a
  second confirmation exception, application result wrapper, or per-cause
  failure taxonomy.
- [ ] 5.2 Implement an applier accepting only
  `EntryAppliedConfirmation | EntryAbsentConfirmation` together with source
  state, a command-bearing `Apply | Replace | Cancel` decision, and sent
  `EntryReconciliationCommand`.
- [ ] 5.3 Implement valid `Apply` from null `current_trade_cycle` so a matching
  `EntryAppliedConfirmation` creates a complete cycle containing the
  decision/confirmation desired entry and calculated quantity.
- [ ] 5.4 Implement valid `Replace` so matching decision, command, and
  `EntryAppliedConfirmation` identities retain the existing cycle ID and
  atomically replace the complete two-field package.
- [ ] 5.5 Implement valid `Cancel` so matching decision, command, and
  `EntryAbsentConfirmation` identities clear the entire
  `current_trade_cycle`.
- [ ] 5.6 Validate variant/confirmation compatibility, strategy-instance
  identity, decision/command/confirmation cycle identity, desired-entry
  equivalence, calculated quantity, and source-state preconditions before
  constructing new state.
- [ ] 5.7 Reject
  `Cancel + sent_command.desired_entry != null + EntryAbsentConfirmation` with
  `EntryReconciliationInvariantError`.
- [ ] 5.8 Raise `EntryReconciliationInvariantError` for every contradictory
  formal success while leaving the input aggregate unmodified and
  domain-value-equivalent to its pre-call snapshot.
- [ ] 5.9 Keep `NoOp`, public client errors, timeout, network failure, protocol
  failure, and missing confirmations outside the applier API.

## 6. Exhaustive Decision, Command, and Transition Tests

- [ ] 6.1 Test all five decision-table rows, including exact `Apply`, `Replace`,
  and `Cancel` payloads, equivalent presence, and both absence cases.
- [ ] 6.2 Test the state model accepts only null `current_trade_cycle` or a
  complete cycle with a required package and rejects
  `CurrentTradeCycle(applied_entry_package=None)` before aggregate/repository
  use.
- [ ] 6.3 Parameterize every one-field `DesiredEntry` difference to prove side,
  source bar, entry, stop, take, and locked profile each cause non-equivalence
  and `Replace`.
- [ ] 6.4 Test successful `Apply` starts only from null
  `current_trade_cycle`, creates no cycle before confirmation, and creates one
  complete acknowledged cycle/package afterward.
- [ ] 6.5 Test successful `Replace` preserves the cycle identity and replaces
  both package fields atomically without an intermediate empty cycle.
- [ ] 6.6 Test successful `Cancel` sets the whole `current_trade_cycle` to null
  and never leaves an empty cycle.
- [ ] 6.7 Test `NoOp` produces no command, needs no confirmation, prohibits an
  apply-only ID, and is distinguishable from command-build failure.
- [ ] 6.8 Test missing `Apply` cycle ID, apply-only IDs supplied to other
  variants, stale `Replace`/`Cancel` cycle IDs, and inconsistent source state
  with explicit invariant failure and no fallback.
- [ ] 6.9 Test every command-bearing decision variant against the wrong
  successful confirmation variant.
- [ ] 6.10 Test
  `Cancel + sent_command.desired_entry != null + EntryAbsentConfirmation`
  raises `EntryReconciliationInvariantError`.
- [ ] 6.11 Test mismatched strategy-instance identity, mismatched trade-cycle
  identity, and replace/cancel target mismatch.
- [ ] 6.12 Test applied confirmations differing in each desired-entry field and
  assert invariant error, unchanged input value, and no state transition.
- [ ] 6.13 Test invalid confirmation quantity with aggregate value equality and
  a pre-call snapshot, without Python object-identity assertions.
- [ ] 6.14 Test that `NoOp` and invariant-failure coverage does not require
  top-level or nested `is` identity and permits an equivalent immutable copy
  where a value is returned.
- [ ] 6.15 Test exact calculated-quantity preservation without `float`
  conversion.

## 7. Dependency Isolation and Verification

- [ ] 7.1 Add architecture tests proving pure reconciliation modules have no
  imports from ABI request/response models, ports or HTTP adapters,
  repositories, keyed coordination, Engine, open-position lookup, handoff,
  orchestrators, bootstrap, or infrastructure.
- [ ] 7.2 Confirm I3 introduces no public-error, timeout, network, protocol,
  null-confirmation, unconfirmed-result, retry, or recovery handling in the
  state applier.
- [ ] 7.3 Confirm no existing ABI client DTO, codec, port, HTTP adapter,
  OpenAPI contract, Runtime orchestrator, repository, mutex, Engine route,
  production composition, processing journal, delivery-map status, HTML
  document, or external ABI repository is changed by the I3 implementation.
- [ ] 7.4 Run focused state-model, reconciliation, I3 model, command-builder,
  success-transition, and architecture tests.
- [ ] 7.5 Run the complete pytest suite, Ruff, mypy, and Python compilation
  checks.
- [ ] 7.6 Run strict validation for `runtime-entry-reconciliation-v1` and
  repository-wide OpenSpec validation.
- [ ] 7.7 Review the final implementation diff to confirm only the
  current-cycle model and pure I3 components change, with client adaptation and
  orchestration deferred to I4.
