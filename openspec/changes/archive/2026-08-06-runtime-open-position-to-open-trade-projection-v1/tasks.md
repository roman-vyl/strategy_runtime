## 1. Orchestrator

- [x] 1.1 Orchestrator applies the existing first-fill transition when a
  resolved position is open, before routing, inside the existing keyed
  critical section.
- [x] 1.2 A changed transition result is saved through the repository
  before the router is called; an unchanged result is not saved, and a
  transition failure propagates without calling the router.

## 2. Router

- [x] 2.1 Router requires a frozen entry context for an open position;
  without one it fails closed exactly as before, with no Engine call.
- [x] 2.2 Router builds the open-trade request from the registered spec
  snapshot, the current committed bar, and the frozen entry context —
  never from the live deployment, never including `average_entry_price`.
- [x] 2.3 Router calls the open-trade Engine port once and returns the
  typed projection, wrapping the response without interpreting it.
- [x] 2.4 Closed-position routing (live-entry) is unchanged.

## 3. Tests

- [x] 3.1 Focused orchestrator and router tests covering sections 1 and 2.
- [x] 3.2 One production semantic-path test driving a positive ABI
  open-position result through to a real Engine call.

## 4. Verification

- [x] 4.1 Full test suite, `ruff check`, `ruff format --check`, `mypy`.
- [x] 4.2 `openspec validate` for this change and `--all`, both `--strict`.

## 5. Follow-Up

- [x] 5.1 Sync affected specs and archive this change after approval.
