## ADDED Requirements

### Requirement: Order lifetime from the Runtime config file
Runtime SHALL read `order_lifetime_bars` once at start from the same config
file as `live_entry_mode`. With `live_entry_mode = touch_trigger` the key SHALL
be required and SHALL be an integer `>= 0`; a missing, negative, fractional,
boolean or non-numeric value SHALL stop Runtime at start. With `ema_anchor` the
key SHALL be optional, validated when present, and unused. Composition SHALL
pass the value to `EntryReconciliationOrchestrator` and to no other component.

#### Scenario: touch_trigger with a lifetime
- **WHEN** the file contains `live_entry_mode = "touch_trigger"` and
  `order_lifetime_bars = 3`
- **THEN** the composed `EntryReconciliationOrchestrator` receives lifetime 3

#### Scenario: touch_trigger without a valid lifetime
- **WHEN** the file contains `live_entry_mode = "touch_trigger"` and the key is
  missing, or is `-1`, `3.0`, `true` or `"3"`
- **THEN** Runtime fails at start with an error, before composition

#### Scenario: ema_anchor
- **WHEN** the mode is `ema_anchor`
- **THEN** a missing key is accepted and a present valid key is accepted and
  unused
