## ADDED Requirements

### Requirement: Recovery states accept an optional cycle execution state

Runtime's recovery-state client MUST accept an optional `cycle_execution_state` in the
`entry_order_live` and `position_open` responses with the same strict decoding as the
applied response, and MUST keep rejecting it in every other recovery state.

#### Scenario: entry_order_live or position_open with the field
- **WHEN** the response carries a well-formed `cycle_execution_state`
- **THEN** the typed response exposes it unchanged

#### Scenario: Other recovery state with the field
- **WHEN** `entry_order_not_found`, `terminal_without_fill` or `terminal_after_fill` carries it
- **THEN** the response fails decoding
