# Strategy Engine specification-hash contract cleanup plan

## Status

Planned. No Engine code is changed by this document. Backward compatibility is
not required.

## Decision

Remove every specification/configuration hash from the Runtime ↔ Strategy Engine live-entry and open-trade contracts. In particular:

- remove `source_config_hash`;
- reject introducing `spec_revision_hash` or `deployment_revision_hash`;
- do not replace them with another configuration correlation field;
- do not change `market_data_hash` in this plan; its separate removal is defined by `26_engine_market_data_hash_contract_cleanup_plan.md`.

The Runtime utility-layer hash remains internal to Runtime utility functions and is outside Engine scope.

## Target contracts

### Live-entry request

Contains only the complete strategy object, market object, and exact target bar required for calculation.

### Live-entry response

Contains the entry projection (`long_plan`, `short_plan`) and no specification/configuration hash. Removal of `market_data_hash` is handled by plan 26.

### Open-trade request

Contains the complete strategy object required for the calculation, market, exact target bar, and entry/execution context. It contains no specification/configuration hash.

### Open-trade response

Contains position-management calculation output and no specification/configuration hash. Removal of `market_data_hash` is handled by plan 26.

## Removal steps

- [ ] 1. Audit active Engine OpenSpec, OpenAPI, domain DTOs, HTTP models, adapters, application services, serializers, and tests for `source_config_hash`, `spec_revision_hash`, and `deployment_revision_hash`.
- [ ] 2. Update the active Engine OpenSpec before code changes: remove configuration-hash requirements, examples, validation scenarios, and response echoes.
- [ ] 3. Remove `source_config_hash` from live-entry response domain models and transport models.
- [ ] 4. Remove `source_config_hash` from open-trade request receipt/context models and transport models.
- [ ] 5. Remove `source_config_hash` from open-trade response models if present.
- [ ] 6. Remove hash generation, canonicalization, comparison, and mismatch-validation paths that exist only for the cross-service contract.
- [ ] 7. Preserve any internal Engine hashing only if it has a proven local purpose unrelated to Runtime contracts; rename/document it as internal and do not serialize it.
- [ ] 8. Do not couple this cleanup to `market_data_hash`; apply plan 26 separately.
- [ ] 9. Update OpenAPI schemas and JSON examples so extra configuration-hash fields are rejected where strict models are used.
- [ ] 10. Update unit, application, adapter, and API tests to remove configuration-hash fixtures and echo assertions.
- [ ] 11. Add negative contract tests showing that removed configuration-hash fields are not accepted or emitted.
- [ ] 12. Run the full Engine verification suite and compare trading calculations before and after; outputs other than removed fields must remain identical.
- [ ] 13. Update Engine architecture/audit documentation and mark this plan complete with exact files and verification results.

## Acceptance criteria

- no Runtime-facing Engine request or response contains a specification/configuration hash;
- no Engine calculation depends on such a hash;
- no replacement correlation ID/hash is introduced;
- `market_data_hash` is governed by the separate cleanup plan 26;
- all calculation outputs are parity-identical apart from removed transport fields;
- active OpenSpec and OpenAPI describe the same cleaned contract.

## Deferred

The immutable/frozen strategy-definition lifecycle is intentionally not designed in this plan. It will be specified separately after this boundary cleanup is accepted.
