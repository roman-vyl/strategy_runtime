## ADDED Requirements

### Requirement: Resolver carries a proven closure transiently
The resolver SHALL pass ABI's closure unchanged on the resolved state, and SHALL NOT persist it. With no current trade cycle no lookup is made and there is no closure.

#### Scenario: Closure from ABI
- **WHEN** ABI returns `position_open: false` with a closure
- **THEN** the resolved state exposes `position_open = False` and that closure
