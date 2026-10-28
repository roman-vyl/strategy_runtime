## 1. strategy_runtime

- [x] 1.1 Read service: catalog snapshot + one state read per accepted deployment, mapping per the spec.
- [x] 1.2 Route `GET /v1/strategy-instance-states`, response models, failure mapping; OpenAPI.
- [x] 1.3 Tests: flat, never processed, entry_pending, in_position, recovery entry and close, catalog order, not ready, catalog unavailable, state unavailable, internal error, 405, no writes and no ABI/Engine call.
- [x] 1.4 `make test` and `make lint`.

## 2. Verification on the Mac (on owner's word only)

- [ ] 2.1 Deploy Runtime. The route answers for all instances; the states match the open positions and entry orders seen on Bybit demo.
