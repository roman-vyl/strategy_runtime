# Runtime payload `contract_version` boundary decision

Date: 2026-07-23

## Decision

Strategy Runtime does not transmit, receive, validate, persist, or propagate a
payload-level `contract_version` in Runtime ↔ Engine information exchange.

Transport compatibility is governed by the deployed HTTP endpoint and its
OpenAPI/schema contract. Runtime does not support multiple incompatible payload
shapes on one endpoint and therefore does not require an in-body version switch.

## Runtime consequences

`contract_version` is prohibited in:

- Runtime → Engine requests;
- Engine → Runtime responses expected by Runtime;
- Runtime state and trade-cycle objects;
- entry or position-management recipes;
- processing journal events;
- internal orchestration objects and typed errors.

No replacement identifier or hash is introduced.

## Scope boundary

Historical audits may still describe removed Engine
contracts containing `contract_version`. They are not normative Runtime
contracts. Cleanup of the separate Strategy Engine repository is specified in
`docs/external-engine-plans/27_engine_contract_version_cleanup_plan.md`.
