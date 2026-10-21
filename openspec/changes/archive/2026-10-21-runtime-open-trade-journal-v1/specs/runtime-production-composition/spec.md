## ADDED Requirements

### Requirement: Production wires the open-trade journal ports
Production composition SHALL pass the JSONL processing journal as the `OpenTradeEvaluationJournalPort` of the strategy runtime orchestrator and as the `ProtectionAppliedJournalPort` of the position management orchestrator.

#### Scenario: Production startup
- **WHEN** the production application is composed
- **THEN** both ports are the same JSONL processing journal used for the other Runtime events
