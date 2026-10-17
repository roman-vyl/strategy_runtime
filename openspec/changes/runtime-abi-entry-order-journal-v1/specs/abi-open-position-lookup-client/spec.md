## ADDED Requirements

### Requirement: Open-position response accepts an optional executed quantity

Runtime's open-position client MUST accept an optional `executed_quantity` (exact-decimal
text, or `null`) when `position_open` is `true`, and MUST reject a non-null value when
`position_open` is `false`.

#### Scenario: Open position with executed quantity
- **WHEN** `position_open` is `true` and `executed_quantity` is `0.01`
- **THEN** the lookup response exposes `executed_quantity` `0.01`

#### Scenario: Closed position
- **WHEN** `position_open` is `false` and `executed_quantity` is non-null
- **THEN** the response fails decoding
