## ADDED Requirements

### Requirement: Runtime live-entry mode from the config file
Strategy Runtime SHALL read `live_entry_mode` once at start from the TOML file named by `RUNTIME_CONFIG_PATH`, with
allowed values `ema_anchor` and `touch_trigger`, and `ema_anchor` when the path is unset, the file is absent or the key is
absent. It SHALL refuse to start on an unknown value, an unknown key or an unparsable file. The resolved mode SHALL be part
of the Runtime configuration, and no Runtime behaviour SHALL depend on it.

#### Scenario: No config file
- **WHEN** `RUNTIME_CONFIG_PATH` is unset or names a missing file
- **THEN** the Runtime configuration SHALL carry `live_entry_mode = ema_anchor`

#### Scenario: Touch trigger in the file
- **WHEN** the file contains `live_entry_mode = "touch_trigger"`
- **THEN** the Runtime configuration SHALL carry `live_entry_mode = touch_trigger`

#### Scenario: Invalid file
- **WHEN** the file contains `live_entry_mode = "close"`, an unknown key, or does not parse
- **THEN** Runtime SHALL fail at start with an error, before composition

#### Scenario: Behaviour unchanged
- **WHEN** the same closed bars are processed with the mode `ema_anchor` and with `touch_trigger`
- **THEN** every reconciliation decision, outbound request and journal line SHALL be identical
