# entry-reconciliation-execution-bridge Specification

## Purpose
TBD - created by archiving change runtime-production-outbound-adapters-v1. Update Purpose after archive.
## Requirements
### Requirement: Runtime exposes one entry-reconciliation execution bridge
Strategy Runtime SHALL provide a production implementation of the existing
`EntryReconciliationExecutionPort.execute(command, source_state)` contract that
translates one `EntryReconciliationCommand` plus its `source_state` into one
`EntryPackageRequest`, calls the existing `AbiEntryPackagePort` exactly once, and
returns the matching `SuccessfulEntryConfirmation` variant or raises a typed
execution failure.

#### Scenario: Execute one present-package command
- **WHEN** a caller supplies an `EntryReconciliationCommand` with a non-null
  `desired_entry` and a `source_state` carrying a positive
  `risk_multiplier`
- **THEN** the bridge constructs one `EntryPackageRequest` with a present
  `EntryPackageWireDesiredEntry`
- **AND** calls `AbiEntryPackagePort.send` exactly once
- **AND** returns one `SuccessfulEntryConfirmation`

#### Scenario: Execute one absent-package command
- **WHEN** a caller supplies an `EntryReconciliationCommand` with
  `desired_entry = None`
- **THEN** the bridge constructs one `EntryPackageRequest` with
  `desired_entry = None`
- **AND** calls `AbiEntryPackagePort.send` exactly once
- **AND** returns one `SuccessfulEntryConfirmation`

### Requirement: The bridge owns no HTTP transport
The entry-reconciliation execution bridge SHALL NOT own an HTTP client, URL
encoding, timeout configuration, or redirect behavior. It SHALL depend only on
the existing `AbiEntryPackagePort`, the transport-free `EntryPackageRequest`,
and the Runtime command, state, confirmation, and error types.

#### Scenario: Reuse the existing ABI entry-package client
- **WHEN** the bridge executes a command
- **THEN** it invokes the existing `AbiEntryPackagePort.send` and introduces no
  second HTTP transport for the entry-package endpoint

#### Scenario: Remain free of HTTP dependencies
- **WHEN** the bridge module is inspected
- **THEN** it has no `httpx` import or HTTP client construction
- **AND** accepts any `AbiEntryPackagePort` fake without transport configuration

### Requirement: Risk multiplier is sourced from source_state only
The bridge SHALL read `risk_multiplier` from `source_state.risk_multiplier` and
SHALL NOT read it from the command, the desired entry, deployment configuration,
or any other source.

#### Scenario: Source the operational risk multiplier
- **WHEN** the bridge constructs an `EntryPackageRequest`
- **THEN** `risk_multiplier` equals `source_state.risk_multiplier`
- **AND** the command carries no risk multiplier field

#### Scenario: Keep risk multiplier mandatory one-way
- **WHEN** the bridge constructs an absent-package request
- **THEN** `risk_multiplier` remains a required positive exact-decimal string
  sourced from `source_state`
- **AND** the bridge does not replace it with null or omit it

### Requirement: Desired entry maps bidirectionally between domain and wire shapes
The bridge SHALL map the domain `DesiredEntry` into the ABI-facing
`EntryPackageWireDesiredEntry` for the outbound request and SHALL map the
returned `EntryPackageWireDesiredEntry` back into the domain `DesiredEntry` for
the confirmation, without bypassing either model's invariants or inventing
additional rules.

#### Scenario: Map a present desired entry outbound
- **WHEN** the bridge constructs a present-package request
- **THEN** `desired_entry` is an `EntryPackageWireDesiredEntry` with exactly the
  six fields of the command's `DesiredEntry`
- **AND** no timestamp range, price-order, or profile-content rule is added

#### Scenario: Map an applied desired entry inbound
- **WHEN** `AbiEntryPackagePort.send` returns `EntryPackageApplied`
- **THEN** the bridge returns `EntryAppliedConfirmation` whose
  `applied_desired_entry` is a domain `DesiredEntry` constructed through its
  existing invariants
- **AND** `calculated_quantity` is preserved as exact-decimal text

#### Scenario: Map an absent acknowledgement
- **WHEN** `AbiEntryPackagePort.send` returns `EntryPackageAbsent`
- **THEN** the bridge returns `EntryAbsentConfirmation` with the originating
  `strategy_instance_id` and `trade_cycle_id`

### Requirement: Unconfirmed outcomes raise a typed execution failure
The bridge SHALL raise `EntryReconciliationExecutionError` for any ABI public
error, timeout, network failure, or protocol failure. The bridge SHALL NOT
retry, mutate state, or return a confirmation for an unconfirmed outcome.
`EntryPackagePublicError` is a typed dataclass result value returned by
`AbiEntryPackagePort.send`, not a raised exception: the bridge constructs
`EntryReconciliationExecutionError(public_error=result)` directly from that
value, and no `__cause__` chain applies because nothing was caught or
re-raised. `AbiEntryPackageTimeout`, `AbiEntryPackageNetworkFailure`, and
`AbiEntryPackageProtocolError` are raised exceptions from `send`: the bridge
catches each and raises `EntryReconciliationExecutionError(...) from <original
exception>`, preserving the original exception as `__cause__`.

#### Scenario: Propagate a public ABI error
- **WHEN** `AbiEntryPackagePort.send` returns an `EntryPackagePublicError`
  result value
- **THEN** the bridge constructs `EntryReconciliationExecutionError` from that
  result value
- **AND** no exception was caught or re-raised, so no `__cause__` is required
- **AND** the bridge returns no confirmation

#### Scenario: Propagate a transport or protocol failure
- **WHEN** `AbiEntryPackagePort.send` raises `AbiEntryPackageTimeout`,
  `AbiEntryPackageNetworkFailure`, or `AbiEntryPackageProtocolError`
- **THEN** the bridge catches the raised exception and raises
  `EntryReconciliationExecutionError`
- **AND** the original raised exception is preserved as `__cause__`

#### Scenario: Do not retry an unconfirmed outcome
- **WHEN** an ABI call fails or is rejected
- **THEN** the bridge calls `AbiEntryPackagePort.send` exactly once
- **AND** performs no retry, fallback, or compensating call

### Requirement: The bridge owns no mutex, repository, or state mutation
The bridge SHALL NOT acquire the keyed mutex, load or save repository state,
apply a confirmation to `CurrentTradeCycle`, or otherwise mutate Runtime state.
Reconciliation decisions remain the responsibility of the existing
`EntryReconciliationOrchestrator`.

#### Scenario: Keep state ownership outside the bridge
- **WHEN** the bridge executes a command
- **THEN** it acquires no keyed mutex
- **AND** performs no repository load or save
- **AND** applies no confirmation to `CurrentTradeCycle` or
  `StrategyInstanceRuntimeState`
- **AND** does not reproduce `NoOp`/`Apply`/`Replace`/`Cancel` decisions

### Requirement: Bridge behavior is verified by typed translation tests
The bridge layer SHALL include unit/translation tests against a fake
`AbiEntryPackagePort` covering command-to-request mapping, both success
confirmations, every failure mapping, and the no-retry/no-state-mutation
invariants. It SHALL NOT be covered by fake-HTTP tests because it owns no HTTP
behavior.

#### Scenario: Verify command-to-request translation
- **WHEN** translation tests exercise present and absent commands
- **THEN** they assert the exact `EntryPackageRequest` fields, the sourced
  `risk_multiplier`, and the bidirectional `DesiredEntry` mapping

#### Scenario: Verify confirmation and failure mapping
- **WHEN** the fake `AbiEntryPackagePort` returns each result or raises each
  typed exception
- **THEN** tests assert the matching `SuccessfulEntryConfirmation` variant or
  `EntryReconciliationExecutionError`
- **AND** for the `EntryPackagePublicError` result value, the error is
  constructed directly with no `__cause__` asserted
- **AND** for each raised exception (`AbiEntryPackageTimeout`,
  `AbiEntryPackageNetworkFailure`, `AbiEntryPackageProtocolError`), the
  original exception is preserved as `__cause__`

#### Scenario: Verify no HTTP ownership
- **WHEN** the bridge is tested
- **THEN** no fake HTTP server is used
- **AND** tests inject only a fake `AbiEntryPackagePort`

