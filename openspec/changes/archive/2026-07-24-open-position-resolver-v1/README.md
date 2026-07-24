# Open Position Resolver v1

This change records the implemented second semantic Runtime step after
strategy-instance state get-or-create.

For one runtime state, the resolver queries ABI exactly once using only
`strategy_instance_id`, attaches the returned current-position facts to a
transient view, and returns that view to the same orchestrator method. It does
not route, call Engine, or mutate repository state.
