## ADDED Requirements

### Requirement: Applied response accepts optional entry-order identifiers

Runtime's entry-package client MUST accept optional `order_link_id` and `order_id` in the `entry_package_applied` response, decode each as a non-empty string when present, carry them on the applied confirmation, and not persist them.

#### Scenario: Response without identifiers
- **WHEN** the applied response has neither field
- **THEN** it decodes as before and both confirmation values are `None`

#### Scenario: Response with identifiers
- **WHEN** the applied response carries both fields
- **THEN** the confirmation exposes them unchanged

#### Scenario: Invalid identifier
- **WHEN** either field is an empty string or not a string
- **THEN** the response fails decoding like any other malformed response
