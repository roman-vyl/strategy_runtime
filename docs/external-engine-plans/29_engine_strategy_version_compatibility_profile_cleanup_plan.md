# Plan 29 — Engine strategy_version and compatibility_profile cleanup

## Scope

Remove `strategy_version` and `compatibility_profile` from Strategy Engine live-entry and open-trade request/response contracts, DTOs, validators, mappers, OpenAPI schemas, examples, tests, and internal routing where they are not backed by real parallel implementations. Do not modify Engine code from the Runtime repository.

## Target contract

The strategy envelope contains only:

```text
strategy
- strategy_id
- instance_id, only while the Engine contract still requires it
- raw_spec
```

`strategy_id` selects the sole supported implementation and the schema/semantics of `raw_spec`.

## Required audit before edits

1. Locate every parser, DTO, schema and test using either field.
2. Verify there is no real registry with multiple implementations under one `strategy_id`.
3. Verify there is no real parser/adapter selected by `compatibility_profile`.
4. If such mechanisms exist, replace them with explicit distinct `strategy_id` values or migrate to one canonical schema before deletion.

## Required changes

- Remove both fields from live-entry and open-trade request schemas.
- Remove request echo fields from responses.
- Remove validation and mismatch errors for both fields.
- Remove both fields from any source-configuration hash basis; plan 25 already removes those hashes from the Runtime boundary.
- Update OpenAPI, examples, fixtures, integration tests and contract snapshots.
- Keep market coordinates and `target_bar_open_time_ms` unchanged.
- Do not reintroduce payload `contract_version`, spec hashes, or compatibility aliases.

## Acceptance criteria

- Requests containing only `strategy_id`, `raw_spec`, market coordinates and target bar execute successfully.
- Old payloads containing either removed field are rejected or ignored according to one explicitly documented migration policy; preferred policy is fail closed during cutover.
- No Engine branch chooses implementation or parser by either removed field.
- Runtime and Engine contract fixtures agree exactly.
