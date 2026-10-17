## ADDED Requirements

### Requirement: Applied response accepts an optional cycle execution state

Runtime's entry-package client MUST accept an optional `cycle_execution_state` in the
`entry_package_applied` response, decode it strictly (exact keys, exact-decimal text,
nullable `stop_loss`/`take_profit`) and expose it on the applied confirmation as a
transient value that is never persisted.

#### Scenario: Old-shape response
- **WHEN** the applied response has no `cycle_execution_state`
- **THEN** it decodes exactly as before and the transient value is `None`

#### Scenario: New-shape response
- **WHEN** the applied response carries a well-formed `cycle_execution_state`
- **THEN** the confirmation exposes it unchanged

#### Scenario: Malformed inner object
- **WHEN** `cycle_execution_state` has an unknown key or a non-string quantity
- **THEN** the response fails decoding like any other malformed response
