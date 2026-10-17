## ADDED Requirements

### Requirement: Applied record links the evaluation and the order

The `entry_package_applied` payload MUST also contain `bar_open_time_ms` of the committed bar whose processing sent the apply, and `order_link_id` and `order_id` exactly as received from ABI or `null` when not received. Runtime MUST write the record when the applied response carries any of the four entry-order values or either identifier, and MUST NOT use these values in any decision or store them in durable state.

#### Scenario: Same bar as the evaluation
- **WHEN** a bar's processing journals `live_entry_evaluated` and then receives `entry_package_applied`
- **THEN** the `entry_package_applied` record has the same `strategy_instance_id` and `bar_open_time_ms` as that `live_entry_evaluated` event

#### Scenario: Identifiers received
- **WHEN** ABI returns `order_link_id` and `order_id`
- **THEN** the record carries them verbatim next to `trade_cycle_id` and the four values

#### Scenario: Identifiers not received
- **WHEN** ABI returns the four values without identifiers
- **THEN** the record is written with `order_link_id` and `order_id` equal to `null`

#### Scenario: Nothing received
- **WHEN** the applied response has none of the four values and no identifier, or the outcome is cancel, absent or error
- **THEN** no record is written
