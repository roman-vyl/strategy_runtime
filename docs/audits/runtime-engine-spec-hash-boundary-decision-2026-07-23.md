# Runtime ↔ Engine specification-hash boundary decision

Date: 2026-07-23

## Decision

Runtime does not send or receive specification/configuration hashes across the Strategy Engine boundary.

Removed from the target Runtime contract:

- `source_config_hash`;
- `spec_revision_hash`;
- any future `deployment_revision_hash` alias.

`market_data_hash` is also excluded from Runtime information exchange. Runtime does not persist, compare, or forward it.

Any deployment-content hash already used by utility functions remains private to the utility layer. It must not be added to `StrategyBarProcessingUnit`, `StrategyInstanceRuntimeState`, trade-cycle state, recipes, or Engine HTTP DTOs.

## Engine follow-up

No Engine code is changed in this repository. Engine-side cleanup is specified separately in:

`/mnt/data/engine_hash_contract_cleanup/docs/25_engine_spec_hash_contract_cleanup_plan.md`

## Deferred topic

The lifecycle and persistence rules for an immutable/frozen strategy definition are intentionally deferred to a separate design discussion.
