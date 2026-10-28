## ADDED Requirements

### Requirement: Runtime reports the trade state of every deployed instance
Strategy Runtime SHALL expose `GET /v1/strategy-instance-states`. For every accepted deployment of the catalog, in catalog order, the response SHALL contain one item with exactly `strategy_instance_id`, `trade_state`, `trade_cycle_id`, `side`, `first_fill_at_ms` and `recovery_pending`, read from the stored state of that instance:

- `trade_state` is `flat` when the state has no current trade cycle or does not exist, `entry_pending` when the current cycle has no frozen executed-entry context, and `in_position` when it has one;
- `trade_cycle_id` and `side` are the current cycle's identity and the side of its applied desired entry, both `null` when flat;
- `first_fill_at_ms` is the frozen context's first fill time when in position, else `null`;
- `recovery_pending` is `entry` when a pending entry-recovery marker exists, `close` when a pending close-recovery marker exists, else `null`.

#### Scenario: Entry order placed
- **WHEN** an instance's current cycle has an applied entry package and no frozen executed-entry context
- **THEN** its item has `trade_state: "entry_pending"`, the cycle id, the entry side and `first_fill_at_ms: null`

#### Scenario: In position
- **WHEN** an instance's current cycle has a frozen executed-entry context
- **THEN** its item has `trade_state: "in_position"`, the cycle id, the entry side and the first fill time

#### Scenario: Flat or never processed
- **WHEN** an instance has no current cycle, or no stored state yet
- **THEN** its item has `trade_state: "flat"` and `null` cycle id, side and first fill time

#### Scenario: Recovery marker
- **WHEN** an instance has a pending entry-recovery or close-recovery marker
- **THEN** its item has `recovery_pending` `entry` or `close`, independently of `trade_state`

### Requirement: The trade-state route is Runtime's own read-only view
The route SHALL read the deployment catalog once and each instance's stored state once, and SHALL NOT write state, the processing journal or the catalog, touch the intake queue or any per-instance mutex, or call ABI, Strategy Engine or the exchange. It SHALL describe Runtime's state as of its last processed bar.

#### Scenario: No side effects and no exchange call
- **WHEN** the route is served
- **THEN** nothing is written and no ABI, Engine or exchange request is made

#### Scenario: Other methods are not allowed
- **WHEN** a client sends `POST`, `PUT`, `PATCH` or `DELETE` to `/v1/strategy-instance-states`
- **THEN** Runtime returns `405 Method Not Allowed`

### Requirement: The trade-state route reports failures explicitly
Strategy Runtime SHALL NOT return a partial list. It SHALL answer `503 {"status":"not_ready"}` before startup readiness, `503 {"status":"catalog_unavailable"}` when the catalog cannot be read, `503 {"status":"state_unavailable"}` when the state store cannot be read, and `500 {"status":"internal_error"}` on any other failure, with the exception logged.

#### Scenario: State store unreadable
- **WHEN** reading any instance's stored state fails
- **THEN** Runtime returns `503 {"status":"state_unavailable"}` and no items
