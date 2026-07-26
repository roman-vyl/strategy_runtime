## ADDED Requirements

### Requirement: Deployment risk multiplier is required top-level configuration
Every Runtime deployment document SHALL contain a top-level
`risk_multiplier` field whose value is a positive exact-decimal string.

#### Scenario: Preserve a valid user multiplier
- **WHEN** a candidate contains a valid top-level positive exact-decimal string such as `"1"`, `"0.25"`, `"+2.00"`, or `"1e-1"`
- **THEN** the accepted `DeploymentSpecification` contains that exact string lexeme
- **AND** the catalog does not convert it through binary floating point or normalize its text

#### Scenario: Reject a missing multiplier
- **WHEN** top-level `risk_multiplier` is absent
- **THEN** the file is classified invalid and excluded fail-closed
- **AND** the catalog supplies no default value

#### Scenario: Do not source multiplier from raw spec
- **WHEN** top-level `risk_multiplier` is absent but `raw_spec` contains a member with that name
- **THEN** the file is still classified invalid
- **AND** the raw-spec member is not promoted into deployment configuration

#### Scenario: Reject null or non-string multiplier
- **WHEN** top-level `risk_multiplier` is null, a JSON number, a boolean, an object, or an array
- **THEN** the file is classified invalid and excluded fail-closed

#### Scenario: Reject non-positive or invalid decimal text
- **WHEN** top-level `risk_multiplier` is empty, whitespace-padded, non-finite, zero, negative, or outside the exact-decimal grammar
- **THEN** the file is classified invalid and excluded fail-closed

## MODIFIED Requirements

### Requirement: Derived immutable deployment identity
Runtime deployment JSON MUST contain `enabled`, `ticker`, `base_timeframe`,
`strategy_id`, `raw_spec`, and top-level `risk_multiplier`, and MUST NOT contain
manually assigned or obsolete identity fields. The catalog MUST derive
`strategy_instance_id` deterministically from only `strategy_id`, `ticker`,
`base_timeframe`, and `raw_spec`.

#### Scenario: Semantic or market input changes
- **WHEN** any identity-basis field changes
- **THEN** the derived `strategy_instance_id` changes

#### Scenario: Formatting or source path changes
- **WHEN** semantic content is unchanged but filename, formatting, or JSON key order changes
- **THEN** the derived `strategy_instance_id` remains unchanged

#### Scenario: Manual identity is supplied
- **WHEN** an input JSON contains `strategy_instance_id`
- **THEN** the file is rejected as containing a forbidden derived field

#### Scenario: Obsolete identity metadata is supplied
- **WHEN** an input JSON contains `strategy_version` or `compatibility_profile`
- **THEN** the file is rejected as containing a forbidden obsolete field

#### Scenario: Additive non-semantic metadata changes
- **WHEN** fields outside `strategy_id`, `ticker`, `base_timeframe`, and `raw_spec` change
- **THEN** the derived `strategy_instance_id` remains unchanged

#### Scenario: Risk multiplier changes
- **WHEN** two otherwise identical valid deployments differ only in top-level `risk_multiplier`
- **THEN** they derive the same `strategy_instance_id`
- **AND** the existing duplicate-identity rule excludes both if they appear in one snapshot
