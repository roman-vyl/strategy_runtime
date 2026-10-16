## 1. strategy_runtime

- [x] 1.1 `adapters/http/models.py`: add `StrategyInstanceItem`, `InvalidDeploymentFileItem`, `DuplicateDeploymentIdentityItem`, `StrategyInstanceListResponse` and `CatalogUnavailableResponse`; no `raw_spec` field.
- [x] 1.2 `adapters/http/app.py`: add parameter `load_deployment_catalog` (callable, default `None`) and a synchronous `GET /v1/strategy-instances` route with the D3 error mapping; no infrastructure imports.
- [x] 1.3 `bootstrap/application.py`: pass the existing `catalog.load_snapshot` to `create_http_app`; no new object or store.

## 2. Tests

- [x] 2.1 HTTP integration: enabled and disabled in one response and catalog order; exact item field set; `enabled` from the file; no `raw_spec` or state fields; empty catalog; `invalid_files` with `error_message` present and `null`; `duplicate_identities` with both paths and neither deployment in the list; per-request reread after a file change.
- [x] 2.2 Errors (including the OpenAPI schema declaring both 503 bodies): `503 not_ready` (not ready and provider missing); `503 catalog_unavailable`; `500 internal_error` for an unexpected exception; `405` for POST/PUT/PATCH/DELETE.
- [x] 2.3 Read-only: provider called once per request; spec files byte-identical after a request. The route receives only the catalog loader, so it has no access to the state repository, journal or queue.
- [x] 2.4 Existing architecture test (`app.py` imports no infrastructure, repository or mutex) still passes; composition test: ready app has the route.
- [x] 2.5 `make verify` and `openspec validate --all --strict` green.
