## ADDED Requirements

### Requirement: Applied response accepts four optional entry-order values

Runtime's entry-package client MUST accept optional `planned_entry_price`, `stop_loss`,
`take_profit` and `quantity` in the `entry_package_applied` response, decode them
strictly, carry them on the applied confirmation, and not persist them.

#### Scenario: Old-shape response
- **WHEN** the applied response has none of the four fields
- **THEN** it decodes exactly as before and the confirmation values are `None`

#### Scenario: New-shape response
- **WHEN** the applied response carries the four fields
- **THEN** the confirmation exposes them unchanged

#### Scenario: Invalid value or unknown key
- **WHEN** a price or quantity is not exact-decimal text, or another unknown key is present
- **THEN** the response fails decoding like any other malformed response
