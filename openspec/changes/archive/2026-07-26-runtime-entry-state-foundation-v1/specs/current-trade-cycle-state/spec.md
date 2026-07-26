## ADDED Requirements

### Requirement: Strategy-instance state owns at most one minimal current cycle
`StrategyInstanceRuntimeState` SHALL contain
`current_trade_cycle: CurrentTradeCycle | null`.

#### Scenario: Represent no Runtime-owned current cycle
- **WHEN** `current_trade_cycle` is null
- **THEN** Runtime state contains no current-cycle identity or applied entry package
- **AND** Runtime makes no claim that an exchange order or real position is absent

#### Scenario: Nest one current cycle
- **WHEN** `current_trade_cycle` is non-null
- **THEN** exactly one complete `CurrentTradeCycle` is nested under that strategy instance
- **AND** the aggregate cannot contain a second concurrent current cycle

### Requirement: Current trade cycle has only the minimal I2 fields
`CurrentTradeCycle` SHALL contain exactly one non-empty
`trade_cycle_id` and `applied_entry_package: AppliedEntryPackage | null` as its
persisted I2 fields.

#### Scenario: Represent a cycle without a recorded applied package
- **WHEN** `applied_entry_package` is null
- **THEN** the cycle still retains its Runtime-owned `trade_cycle_id`
- **AND** Runtime makes no claim about whether ABI or the exchange has an order or position

#### Scenario: Exclude deferred execution state
- **WHEN** a current cycle is modeled in I2
- **THEN** it contains no phase, frozen execution context, filled quantity, remaining quantity, average entry price, fill timestamp, fill ledger, or position-management recipe

### Requirement: Applied entry package is one indivisible nested value
`AppliedEntryPackage` SHALL contain exactly `applied_desired_entry`,
`accepted_risk_multiplier`, and `calculated_quantity`.

#### Scenario: Preserve one singular desired entry
- **WHEN** an applied package is constructed
- **THEN** it contains one complete `DesiredEntry` under `applied_desired_entry`
- **AND** `CurrentTradeCycle` does not duplicate that desired entry as another field
- **AND** no separate long and short applied-entry objects exist

#### Scenario: Preserve acknowledgement decimal lexemes
- **WHEN** valid acknowledgement strings are supplied
- **THEN** `accepted_risk_multiplier` is positive exact-decimal text
- **AND** `calculated_quantity` is finite exact-decimal text
- **AND** both accepted lexemes are retained without binary floating-point conversion or textual normalization

#### Scenario: Reject invalid package fields
- **WHEN** applied desired entry has the wrong type, accepted multiplier is not positive exact-decimal text, or calculated quantity is not finite exact-decimal text
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
The presence or absence of a Runtime current cycle or applied package SHALL NOT
be treated as authoritative proof of exchange order or position existence.

#### Scenario: Current cycle is absent
- **WHEN** `current_trade_cycle` is null
- **THEN** only Runtime ownership state is known
- **AND** an ABI lookup remains authoritative for exchange position facts

#### Scenario: Applied package is absent
- **WHEN** a current cycle exists with `applied_entry_package` null
- **THEN** only the absence of a recorded Runtime package is known
- **AND** Runtime does not infer that ABI or the exchange is flat
