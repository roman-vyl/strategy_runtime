## Context

`FilesystemDeploymentCatalog.load_snapshot()` returns a `DeploymentCatalogSnapshot`:
`scanned_file_count`, `accepted_deployments` (sorted by file name, duplicates removed),
`invalid_files` (`source_path`, `error_code`, `error_message | None`) and
`duplicate_identities` (`strategy_instance_id`, `source_paths`). It raises
`DeploymentCatalogUnavailableError` when the directory cannot be scanned. Runtime already calls
it on every closed bar, so reading it per request adds no new source of truth.

## Decisions

### D1. Route and method
`GET /v1/strategy-instances`. The path is a prefix of the existing first-fill route
`/v1/strategy-instances/{id}/trade-cycles/{cycle}/first-fill`, which is `PUT` only. The two do
not collide. Other methods on the new path return `405`.

### D2. Response (200)
```
{
  "scanned_file_count": 34,
  "strategy_instances": [
    { "strategy_instance_id": "...", "strategy_id": "...", "instrument": "ETHUSDT.P",
      "base_timeframe": "5m", "enabled": true, "source_path": "file.json" }
  ],
  "invalid_files": [ { "source_path": "bad.json", "error_code": "invalid_json",
                       "error_message": "..." | null } ],
  "duplicate_identities": [ { "strategy_instance_id": "...",
                              "source_paths": ["a.json", "b.json"] } ]
}
```
- `strategy_instances`: exactly `accepted_deployments`, in the catalog's order (file name),
  enabled and disabled together. Deployments whose identity is duplicated are not in this list;
  they appear in `duplicate_identities`, which explains why they are missing.
- `invalid_files` and `duplicate_identities` reuse the catalog's own structure and field names.
  `error_message` is passed through as the catalog returns it (may be `null`). No new diagnostic
  format is introduced.
- `enabled` is `DeploymentSpecification.enabled`, read from the spec file. Its semantics and
  source are unchanged. A future move of `enabled` into Runtime operational state is a separate
  decision and will revise this contract then.
- Not included: `raw_spec`, any Runtime state, any derived status.
- All four lists/values are present on every 200; empty collections are `[]`.

### D3. Errors
| Condition | Response |
|---|---|
| Runtime not ready, or the provider is not wired | `503 {"status":"not_ready"}` |
| `DeploymentCatalogUnavailableError` | `503 {"status":"catalog_unavailable"}` |
| Any other exception from the provider | `500 {"status":"internal_error"}`, logged with traceback |

The existing `NotReadyResponse` and `InternalErrorResponse` models are reused; only
`CatalogUnavailableResponse` is new. A spec file that makes `load_snapshot()` itself raise (the
`1e999` defect) therefore surfaces as `500`, which is accepted for V1.

### D4. No side effects
Each GET calls the provider once, synchronously, and reads only the catalog directory. No
caching, no writes, no state-repository access, no queue or mutex interaction, no journal event.
The route is a synchronous `def` (as the first-fill route is), so FastAPI runs it in its thread
pool and the filesystem scan never blocks the event loop.

### D5. Layering
`app.py` receives the provider as a parameter `load_deployment_catalog` (a zero-argument
callable returning a `DeploymentCatalogSnapshot`), maps it to the response models and imports no
infrastructure. `bootstrap/application.py` passes the already constructed
`catalog.load_snapshot`. No new object or store is created. `create_http_app` keeps working when
the parameter is omitted (route answers `503 not_ready`).

## Risks

- `error_message` for `file_read_failed` is `str(OSError)` and can contain a filesystem path.
  The endpoint serves a local network service; the field is passed through as the catalog
  defines it, and tightening it is a catalog change, not part of this step.
- Per-request directory scan: about thirty small files today; no cache by design (D4).
