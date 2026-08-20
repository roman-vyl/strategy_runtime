## MODIFIED Requirements

### Requirement: The five recovery_state values decode strictly, with conditional fields enforced
The adapter SHALL decode a `200` response's `recovery_state` as exactly one of
`entry_order_live`, `entry_order_not_found`, `position_open`,
`terminal_without_fill`, or `terminal_after_fill`. It SHALL enforce ABI's cross-field
invariant: `applied_entry_package` is non-null if and only if the state is
`entry_order_live` or `position_open`; `first_fill_at_ms` and
`average_entry_price` are both non-null if and only if the state is `position_open`.

`entry_order_not_found` SHALL decode only with `applied_entry_package`,
`first_fill_at_ms`, and `average_entry_price` all null. Runtime SHALL represent it as an
observation distinct from `terminal_without_fill`; the decoder SHALL NOT attach terminal
meaning or synthesize an applied package.

#### Scenario: Decode entry_order_live
- **WHEN** HTTP `200` reports `entry_order_live` with a non-null applied package and both
  fill facts null
- **THEN** the adapter returns the matching typed response carrying the package

#### Scenario: Decode position_open
- **WHEN** HTTP `200` reports `position_open` with a non-null applied package and both
  fill facts non-null
- **THEN** the adapter returns the matching typed response carrying package and fill facts

#### Scenario: Decode entry_order_not_found
- **WHEN** HTTP `200` reports `entry_order_not_found` with applied package and both fill
  facts null
- **THEN** the adapter returns the distinct `entry_order_not_found` typed response
- **AND** does not classify it as terminal or absent confirmation

#### Scenario: Decode terminal_without_fill or terminal_after_fill
- **WHEN** HTTP `200` reports either terminal state with applied package and both fill
  facts null
- **THEN** the adapter returns the matching typed response with no package or fill facts

#### Scenario: Reject a response violating the cross-field invariant
- **WHEN** any state's applied-package or fill fields violate the conditional invariant,
  including any non-null conditional field for `entry_order_not_found`
- **THEN** the adapter raises a typed protocol error
- **AND** returns no recovery response

#### Scenario: Reject an unrecognized recovery_state value
- **WHEN** `recovery_state` is not one of the five documented values
- **THEN** the adapter raises a typed protocol error

### Requirement: The adapter exposes one corrective-action call, distinct from the query
The adapter SHALL retain one corrective CANCEL operation backed by the existing
entry-package client. The uncertain-state resolver may call it after
`entry_order_live` for an uncertain removal or after `entry_order_not_found` for an
uncertain APPLY. Both cases SHALL use the same request shape with `desired_entry:null`
and the pending cycle's exact identity; no second write contract is introduced.

#### Scenario: Corrective cancel reuses the existing entry-package client
- **WHEN** the resolver issues a corrective CANCEL for either eligible recovery row
- **THEN** the adapter sends the ordinary existing `EntryPackageRequest` with
  `desired_entry:null` through the existing `AbiEntryPackagePort`
- **AND** preserves the exact strategy instance and pending trade-cycle identity

#### Scenario: The corrective call is not part of the read-only query
- **WHEN** the resolver calls the recovery `query(...)` operation
- **THEN** that call alone never sends CANCEL
- **AND** the resolver decides whether to call the separate corrective operation from the
  returned state and uncertain APPLY/removal context

## RENAMED Requirements

- FROM: `### Requirement: The four recovery_state values decode strictly, with conditional fields enforced`
- TO: `### Requirement: The five recovery_state values decode strictly, with conditional fields enforced`

