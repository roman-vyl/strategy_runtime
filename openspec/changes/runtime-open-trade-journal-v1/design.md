## Context

Pre-entry observability (the template):

- `live_entry_evaluated` — written in `StrategyRuntimeOrchestrator.process` right after the Engine live-entry answer, before ABI, on every evaluated bar; `desired_entry` may be `null`. Port `LiveEntryEvaluationJournalPort`.
- `entry_package_applied` — written in `EntryReconciliationOrchestrator._execute_one` after ABI confirms an Apply, before the confirmation is applied to state and saved. Bar taken from `projection.source.processing_unit.committed_bar.open_time_ms`.

Open-trade flow today (`c9ad922`): the router asks Engine `open-trade` and returns `OpenTradeProjectedStrategyInstance(source, position_management_recipe)`; `process` calls `PositionManagementOrchestrator.execute_with_closure`; the decision is `NoOp`, `ApplyProtection` (ABI `apply_protection` returns `ProtectionAppliedConfirmation.confirmed_protection`) or `ClosePosition`. Nothing is journaled until `trade_cycle_closed`.

Owner decisions (2026-10-19):

1. `side` — explicit trade direction in `open_trade_evaluated`.
2. Engine diagnostics — not journaled (symmetry with `live_entry_evaluated`).
3. `protection_applied` — ABI's current confirmed answer; ABI contract unchanged.
4. Exit price and time — separate change.
5. One OpenSpec per service, Runtime first.

## Goals / Non-Goals

**Goals:** per-bar record of what Engine asked for during an open position; record of every protection ABI confirmed; same mechanics as the pre-entry pair.

**Non-Goals:** diagnostics; exit price/time; any ABI, Engine, decision, state or recovery change; Journal service ingestion; Workbench display; a record for a close command (the close is already covered by `trade_cycle_closed`).

## Decisions

### D1 `open_trade_evaluated` — where and when

Written in `StrategyRuntimeOrchestrator.process`, `OpenTradeProjectedStrategyInstance` branch, before `execute_with_closure`, exactly like `_journal_live_entry` in the live-entry branch. One record per successful Engine open-trade answer, including bars where the decision will be `NoOp`. Not written when the bar is skipped for a pending entry or close recovery, when a closure was detected on resolve, when `entry_bar_open_time_ms` is after the committed bar, or when Engine fails. A later ABI failure does not remove the record.

### D2 `open_trade_evaluated` — payload

```
instrument, timeframe, bar_open_time_ms,
trade_cycle_id,
side,                      # "long" | "short", from frozen_entry_context.desired_entry.side
desired_protection: { stop_price, take_price | null },
close_signal: { active, reason | null, component_id | null, layer | null }
```

`trade_cycle_id` and `side` come from the current cycle's `frozen_entry_context` (the same values sent to Engine). Decimals as exact decimal text, as in `live_entry_evaluated`. Engine `diagnostics` are not written.

### D2a Fidelity: Engine's answer as it is

`desired_protection` and `close_signal` are copied field by field from the decoded Engine response (`OpenTradeProjectionResponse`, held unchanged in `projection.position_management_recipe`), taken right after routing, before any decision code runs. Runtime does not recompute, round, snap to tick, compare, or label them, and the record carries no decision result (no NoOp / Apply / Close field). The only transformation is the one the codec already applies to every Engine price: canonical decimal text (`normalize_decimal_text`: `"100.50"` is written as `"100.5"`, same exact value, no float), identical to `live_entry_evaluated`. `close_signal` strings are written byte for byte; `null` stays `null`.

`side` is not part of the open-trade answer. It is the `side` Runtime sent to Engine in this request, i.e. Engine's own live-entry answer frozen in `frozen_entry_context.desired_entry` when the cycle was opened. It is copied, never derived from prices.

### D3 `protection_applied` — where and when

Written in `PositionManagementOrchestrator.execute_with_closure`, `ApplyProtection` branch, right after `apply_protection` returns and before `apply_position_management_confirmation`; the save stays in the caller. This copies `entry_package_applied`, which is also written after ABI confirmation and before the state is applied and saved. Not written for `NoOp`, `ClosePosition` or when ABI fails.

### D4 `protection_applied` — payload

```
trade_cycle_id,
bar_open_time_ms,          # projection.source.processing_unit.committed_bar.open_time_ms
stop_price, take_price | null   # from ProtectionAppliedConfirmation.confirmed_protection
```

Values come from ABI's current confirmed answer. Today ABI echoes Runtime's command after reconciling with the exchange, and the Runtime codec requires an exact match; the record therefore equals the command, and ABI's contract is not changed.

### D5 Ports and journal mechanics

- `OpenTradeEvaluationJournalPort` in `runtime/orchestrator/ports.py`; `ProtectionAppliedJournalPort` in `runtime/position_management_orchestrator/ports.py`. Both optional constructor arguments (`None` = no journaling), as the existing journal ports.
- `ProcessingJournalEventType.OPEN_TRADE_EVALUATED = "open_trade_evaluated"`, `PROTECTION_APPLIED = "protection_applied"`.
- `JsonlProcessingJournal` methods via `_record`: envelope schema version 2 with `strategy_instance_id`, best effort, a write failure never raises into orchestration and never changes state.
- `bootstrap/application.py` passes the JSONL journal into both.

## Risks / Trade-offs

- A protection confirmed by ABI but followed by a failed save is journaled, and the next bar repeats the Apply and journals it again: two records for one change. Same accepted behaviour as `entry_package_applied`. Readers take the latest record per cycle.
- Best-effort journal: a lost write loses one record; trading is unaffected.
- One `open_trade_evaluated` per bar per open position adds one line per bar per position to `runtime.jsonl`; size is small compared to `live_entry_evaluated`, which already runs every bar.
- The audit document said "after ABI confirmation and save" for `protection_applied`; the code copy of `entry_package_applied` is "after confirmation, before save". This change follows the code.
