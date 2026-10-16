## 1. strategy_runtime

- [ ] 1.1 `adapters/http/models.py`: add `StrategyInstanceItem`, `InvalidDeploymentFileItem`, `DuplicateDeploymentIdentityItem`, `StrategyInstanceListResponse` and `CatalogUnavailableResponse`; no `raw_spec` field.
- [ ] 1.2 `adapters/http/app.py`: add parameter `list_strategy_instances` (callable, default `None`) and a synchronous `GET /v1/strategy-instances` route with the D3 error mapping; no infrastructure imports.
- [ ] 1.3 `bootstrap/application.py`: build the callable over the existing `catalog.load_snapshot` and pass it to `create_http_app`; no new object or store.

## 2. Tests

- [ ] 2.1 HTTP integration: enabled and disabled in one response and catalog order; exact item field set; `enabled` from the file; no `raw_spec` or state fields; empty catalog; `invalid_files` with `error_message` present and `null`; `duplicate_identities` with both paths and neither deployment in the list; per-request reread after a file change.
- [ ] 2.2 Errors: `503 not_ready` (not ready and provider missing); `503 catalog_unavailable`; `500 error` for an unexpected exception; `405` for POST/PUT/PATCH/DELETE.
- [ ] 2.3 Read-only: provider called once per request; state repository, journal and queue untouched.
- [ ] 2.4 Existing architecture test (`app.py` imports no infrastructure, repository or mutex) still passes; composition test: ready app has the route.
- [ ] 2.5 `make verify` and `openspec validate --all --strict` green.
