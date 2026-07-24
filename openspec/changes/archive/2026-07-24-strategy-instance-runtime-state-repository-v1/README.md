# Strategy Instance Runtime State Repository v1

This change records the implemented state-repository capability used as the first
stage of `StrategyRuntimeOrchestrator.process(...)`.

For one `StrategyBarProcessingUnit`, the orchestrator constructs one typed
get-or-create request, calls the repository exactly once, and receives one
`StrategyInstanceRuntimeState` back into the same orchestration method.

The implemented repository is in-memory and synchronized with `RLock`. This
change defines no physical durability guarantee and does not cover state updates,
recipe lifecycle, Engine calls, ABI calls, or trade-cycle transitions.
