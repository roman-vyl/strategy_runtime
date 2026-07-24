# Use Case Router v1

This change records the implemented third semantic Runtime step and its scalar
orchestration.

For one position-resolved processing item, the router validates the
strategy-instance identity chain, selects the Engine use case from
`position_open`, and returns either a live-entry or open-trade typed projection.
It does not persist state, interpret Engine instructions, or call ABI.
