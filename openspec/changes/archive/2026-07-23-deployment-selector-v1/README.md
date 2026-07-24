# deployment-selector-v1

Implemented OpenSpec change for the pure `deployment-selector` capability used by `CommittedBarOrchestrator`.

The selector consumes only one committed-bar event and one immutable catalog snapshot. It filters by deployment-local `enabled` and exact market coordinates; no separate activation model exists.
