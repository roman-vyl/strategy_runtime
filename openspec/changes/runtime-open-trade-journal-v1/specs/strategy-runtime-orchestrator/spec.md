## ADDED Requirements

### Requirement: Every successful open-trade evaluation is journaled
Runtime SHALL write exactly one `open_trade_evaluated` event for every successful Strategy Engine `open-trade` answer, after routing and before position management runs, whatever the following decision. `trade_cycle_id` and `side` SHALL come from the current cycle's frozen entry context; `bar_open_time_ms` SHALL be the committed bar; `desired_protection` and `close_signal` SHALL be Engine's answer unchanged. The record SHALL NOT be used in any decision.

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
