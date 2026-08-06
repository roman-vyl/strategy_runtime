## 1. Router: Open-Trade Projection

- [ ] 1.1 In `StrategyUseCaseRouter.route` (`runtime/routing/router.py`),
  replace the unconditional `raise OpenTradeContextUnavailable(...)` for
  `resolved.position_open` with a branch that reads
  `resolved.runtime_state.current_trade_cycle`: raise
  `OpenTradeContextUnavailable(unit.strategy_instance_id)` when it is `None`
  or its `frozen_entry_context` is `None`; otherwise continue to 1.2.
- [ ] 1.2 Build `OpenTradeProjectionRequest` from
  `resolved.runtime_state.strategy_id`,
  `resolved.runtime_state.registered_spec_snapshot.{raw_spec,instrument,
  base_timeframe}`, `unit.committed_bar.open_time_ms`, and
  `frozen_entry_context.{desired_entry,entry_bar_open_time_ms}`. Do not read
  `unit.deployment` or `resolved.average_entry_price`/`.first_fill_at_ms`
  for this request.
- [ ] 1.3 Call `self._open_trade_engine.project_open_trade(request)`, wrap
  the response's `desired_protection`, `close_signal`, `diagnostics` into
  `PositionManagementRecipe` (import from
  `runtime.recipes.position_management`), and return
  `OpenTradeProjectedStrategyInstance(source=item,
  position_management_recipe=recipe)`.
- [ ] 1.4 Confirm `_validate_instance_binding` still runs before this branch
  and the live-entry branch is untouched.

## 2. Orchestrator: Freeze First Fill Before Routing

- [ ] 2.1 In `StrategyRuntimeOrchestrator.process`
  (`runtime/orchestrator/orchestrator.py`), after
  `resolved = self._open_position_resolver.resolve(state)`, add: when
  `resolved.position_open`, call a new private
  `_ensure_first_fill_frozen(resolved)` and use its return value for the
  rest of `process`.
- [ ] 2.2 Implement `_ensure_first_fill_frozen`: call
  `apply_first_fill(resolved.runtime_state,
  resolved.runtime_state.current_trade_cycle.trade_cycle_id,
  resolved.first_fill_at_ms)` (import from
  `runtime.first_fill.state_applier`); if the result `is` the input state,
  return `resolved` unchanged; otherwise save the result via
  `self._state_repository.save(...)` and return `resolved` with
  `runtime_state` replaced by the saved state (`dataclasses.replace`).
- [ ] 2.3 Do not add any pre-check for `current_trade_cycle is None` or
  `frozen_entry_context` state beyond what `apply_first_fill` itself
  enforces (see design.md).
- [ ] 2.4 Confirm this executes inside the existing
  `self._keyed_mutex_registry.hold(...)` block and before
  `self._use_case_router.route(...)` is called.

## 3. Router and Semantic-Pipeline Tests

- [ ] 3.1 In `tests/unit/runtime/test_semantic_pipeline.py`, retarget
  `test_router_fails_closed_for_open_position_even_with_complete_context`
  to a state built via `frozen_trade_state()` (no
  `frozen_entry_context`) — keep asserting `OpenTradeContextUnavailable`
  and zero calls to both engines; rename it to reflect "missing frozen
  context", not "complete context".
- [ ] 3.2 Add a passing-case test: a resolved state whose current trade
  cycle has a `frozen_entry_context` routes to the `OpenEngine` fixture
  exactly once, returns `OpenTradeProjectedStrategyInstance` with the
  wrapped `PositionManagementRecipe`, and does not call `LiveEngine`.
  Assert the sent `OpenTradeProjectionRequest` has no
  `average_entry_price`/`executed_entry_price` and its fields match
  `registered_spec_snapshot`/`frozen_entry_context`, not
  `unit.deployment`.
- [ ] 3.3 Add a test asserting `StrategyEngineProjectionUnavailable` from
  `OpenEngine` propagates unchanged through the router for the frozen-open
  branch (mirror the existing live-entry transport-failure test).
- [ ] 3.4 Add a helper (e.g. `frozen_trade_state_with_context()`) building a
  `CurrentTradeCycle` whose `frozen_entry_context` is set, for reuse across
  3.2–3.3 and section 4.

## 4. Orchestrator Tests

- [ ] 4.1 In
  `tests/unit/runtime/orchestrator/test_closed_bar_runtime_orchestration.py`,
  update `test_open_trade_raises_without_reconciliation_or_save` (and
  `test_open_trade_cannot_produce_successful_dispatch`): the resolved
  state's current trade cycle starts unfrozen, the router is still a
  `MagicMock` returning `OpenTradeProjectedStrategyInstance` directly, and
  the test now asserts `repo.save_calls` contains exactly one saved state
  (the first-fill freeze) while `ep.calls == []` (no reconciliation) and
  `OpenTradeProjectionUnsupportedError` still propagates.
- [ ] 4.2 Add a test: resolved state's current trade cycle is already
  frozen (matching `first_fill_at_ms`) — `process(...)` calls
  `apply_first_fill` (real, not mocked) and the fake repository's `save` is
  not called before routing.
- [ ] 4.3 Add a test: resolved state's current trade cycle is unfrozen —
  `process(...)` saves exactly one new state with a populated
  `frozen_entry_context` before the router is invoked, and the router
  receives that saved state (assert via a recording router double).
- [ ] 4.4 Add a test: a resolver returning `position_open=True` with
  `first_fill_at_ms` conflicting with an already-frozen context raises
  `FirstFillInvariantError` from `process(...)`, the router is never
  called, and no save occurs.
- [ ] 4.5 Add a test: `position_open=False` never calls `apply_first_fill`
  (spy or count) and behaves exactly as before this change.
- [ ] 4.6 Confirm `test_mutex_released_after_each_exception`'s `open_trade`
  case still releases the mutex with the updated freeze step in play.

## 5. Full Verification

- [ ] 5.1 Run `pytest` for the changed and affected test files (`runtime/
  routing`, `runtime/orchestrator`, `runtime/test_semantic_pipeline.py`),
  then the full suite.
- [ ] 5.2 Run `ruff check` and `ruff format --check`.
- [ ] 5.3 Run `mypy`.
- [ ] 5.4 Run
  `openspec validate runtime-open-position-to-open-trade-projection-v1
  --strict` and `openspec validate --all --strict`.
- [ ] 5.5 Grep the diff for `average_entry_price` and confirm it appears
  only in `runtime/open_position/*` and `infrastructure/abi/*` — never in
  `runtime/routing/router.py`, `runtime/orchestrator/orchestrator.py`, or
  `runtime/engine/open_trade.py`.
