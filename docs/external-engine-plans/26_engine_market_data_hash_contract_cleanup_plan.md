# Strategy Engine `market_data_hash` contract cleanup plan

## Status

Planned only. No Strategy Engine code is changed by the Runtime-side work.

## Goal

Remove `market_data_hash` from live Runtime-facing Strategy Engine request/response contracts without introducing a replacement hash or correlation ID.

## Boundary rule

Strategy Runtime sends calculation inputs and receives calculation results. It does not receive, compare, persist, or forward a market-data hash.

## Steps

- [ ] 1. Audit all Engine occurrences of `market_data_hash` and classify them as MDS-internal, Engine-internal, Research-facing, or Runtime-facing.
- [ ] 2. Remove `market_data_hash` from the active live-entry Runtime-facing OpenSpec response.
- [ ] 3. Remove `market_data_hash` from the active open-trade Runtime-facing OpenSpec response.
- [ ] 4. Remove the field from Runtime-facing domain result DTOs and transport models.
- [ ] 5. Remove Runtime-facing serialization and OpenAPI schema properties.
- [ ] 6. Remove validation that requires a non-empty `market_data_hash` for live Runtime responses.
- [ ] 7. Remove response echo/provenance tests that assert the field is returned to Runtime.
- [ ] 8. Keep any MDS-internal hash calculation only where Engine itself still needs it; do not leak it into Runtime-facing results.
- [ ] 9. Audit Research Service and backtest endpoints separately before removing market-data provenance from those contracts.
- [ ] 10. Add negative contract tests proving Runtime-facing requests/responses reject or omit `market_data_hash`, according to the final strict DTO policy.
- [ ] 11. Run trading-result parity tests and prove that removing the field changes no entry plan, protection, close signal, or diagnostic calculation.
- [ ] 12. Update Engine architecture docs and mark the Runtime boundary cleanup complete.

## Definition of done

- Runtime-facing Engine schemas contain no `market_data_hash`.
- Engine calculations remain unchanged.
- No replacement provenance hash or request/response correlation field is introduced.
- Research/backtest provenance remains explicitly out of scope until separately decided.
