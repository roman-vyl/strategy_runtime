## ADDED Requirements

### Requirement: Every successful open-trade evaluation is journaled
Runtime SHALL write exactly one `open_trade_evaluated` event for every successful Strategy Engine `open-trade` answer, after routing and before position management runs, whatever the following decision. `trade_cycle_id` and `side` SHALL come from the current cycle's frozen entry context; `bar_open_time_ms` SHALL be the committed bar; `desired_protection` and `close_signal` SHALL be Engine's answer exactly as received on the wire, prices as Engine's own text before any Runtime normalization, without recomputation, rounding, reformatting, comparison or a decision label. Decisions SHALL keep using the normalized protection and SHALL NOT read the wire text. `side` SHALL be copied from the frozen desired entry sent to Engine in the same request. The record SHALL NOT be used in any decision.

#### Scenario: Record equals Engine's answer
- **WHEN** Engine answers with `desired_protection` `{stop_price: "101.50", take_price: null}` and `close_signal` `{active: false, reason: null, component_id: null, layer: null}`
- **THEN** the record has `desired_protection` `{stop_price: "101.50", take_price: null}` and the same `close_signal`, with no added, recomputed or decision field
- **AND** the decision for that bar still compares the normalized value `101.5`

#### Scenario: Side is the side sent to Engine
- **WHEN** the current cycle's frozen desired entry has `side: "short"`
- **THEN** the record has `side: "short"`, copied from the frozen entry context, not derived from prices

#### Scenario: Engine asks for no change
- **WHEN** Engine's answer equals the current protection and the close signal is inactive
- **THEN** one `open_trade_evaluated` event is written for the bar

#### Scenario: Engine asks to close
- **WHEN** Engine's close signal is active
- **THEN** one `open_trade_evaluated` event with the active close signal is written before the close command is sent

#### Scenario: Later ABI step fails
- **WHEN** the evaluation succeeds and the following ABI call fails
- **THEN** the `open_trade_evaluated` event for that bar is still present

#### Scenario: No open-trade evaluation happened
- **WHEN** the bar is skipped because of a pending entry or close recovery, a closure is detected on resolve, the frozen entry bar is after the committed bar, the instance is routed to live-entry, or Engine `open-trade` fails
- **THEN** no `open_trade_evaluated` event is written for that instance and bar
