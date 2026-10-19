## Context

Pre-entry observability (the template):

- `live_entry_evaluated` — written in `StrategyRuntimeOrchestrator.process` right after the Engine live-entry answer, before ABI, on every evaluated bar; `desired_entry` may be `null`. Port `LiveEntryEvaluationJournalPort`.
- `entry_package_applied` — written in `EntryReconciliationOrchestrator._execute_one` after ABI confirms an Apply, before the confirmation is applied to state and saved. Bar taken from `projection.source.processing_unit.committed_bar.open_time_ms`.

Open-trade flow today (`c9ad922`): the router asks Engine `open-trade` and returns `OpenTradeProjectedStrategyInstance(source, position_management_recipe)`; `process` calls `PositionManagementOrchestrator.execute_with_closure`; the decision is `NoOp`, `ApplyProtection` (ABI `apply_protection` returns `ProtectionAppliedConfirmation.confirmed_protection`) or `ClosePosition`. Nothing is journaled until `trade_cycle_closed`.

Owner decisions (2026-10-19):

1. `side` — explicit trade direction in `open_trade_evaluated`.
2. Engine diagnostics — not journaled (symmetry with `live_entry_evaluated`).
3. `protection_applied` — first agreed as ABI's current answer without a contract change; revised by the owner the same day (15:28): full symmetry with `entry_package_applied`, including the identifiers of the concrete protective orders. The ABI contract is extended for that.
4. Exit price and time — separate change.
5. One OpenSpec per service, Runtime first.

## Goals / Non-Goals

**Goals:** per-bar record of what Engine asked for during an open position; record of every protection ABI confirmed; same mechanics as the pre-entry pair.

**Non-Goals:** diagnostics; exit price/time; any Engine, decision, state or recovery change; Journal service ingestion; Workbench display; a record for a close command (the close is already covered by `trade_cycle_closed`).

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

`trade_cycle_id` and `side` come from the current cycle's `frozen_entry_context` (the same values sent to Engine). Prices as Engine's own text (D2a). Engine `diagnostics` are not written.

### D2a Fidelity: Engine's answer as it is

`desired_protection` and `close_signal` are Engine's open-trade answer exactly as Engine sent it (owner decision 2026-10-19, option 1a). Runtime does not recompute, round, snap to tick, compare, reformat or label them, and the record carries no decision result (no NoOp / Apply / Close field).

Today `DesiredProtection.__post_init__` rewrites every price to canonical decimal text (`normalize_decimal_text`: `"105.150"` becomes `"105.15"`). The record must not carry that rewrite. So the Engine wire codec keeps the validated wire strings of `desired_protection` (`stop_price`, `take_price`) as they arrived, in a separate transient field of `OpenTradeProjectionResponse` (`engine_desired_protection_text`), carried unchanged through `PositionManagementRecipe` to the journal call. The normalized `DesiredProtection` stays the only input of decisions, commands and state; nothing that decides reads the wire text. `close_signal` strings are already kept byte for byte; `null` stays `null`. `live_entry_evaluated` is not changed by this change.

`side` is not part of the open-trade answer. It is the `side` Runtime sent to Engine in this request, i.e. Engine's own live-entry answer frozen in `frozen_entry_context.desired_entry` when the cycle was opened. It is copied, never derived from prices.

### D3 `protection_applied` — where and when

Written in `PositionManagementOrchestrator.execute_with_closure`, `ApplyProtection` branch, right after `apply_protection` returns and before `apply_position_management_confirmation`; the save stays in the caller. This copies `entry_package_applied`, which is also written after ABI confirmation and before the state is applied and saved. Not written for `NoOp`, `ClosePosition` or when ABI fails.

### D4 `protection_applied` — payload

```
trade_cycle_id,
bar_open_time_ms,                 # projection.source.processing_unit.committed_bar.open_time_ms
requested_protection: { stop_price, take_price | null },   # ApplyProtectionCommand.desired_protection sent by Runtime
confirmed_protection: { stop_price, take_price | null },   # ProtectionAppliedConfirmation.confirmed_protection from ABI
position_quantity,                # protection_orders.quantity: position size the legs protect
stop_order: { order_id, trigger_price },
take_order: { order_id, trigger_price }
```

Requested and confirmed levels are two separate facts, both written even though today's codec requires them to be equal; a reader never has to assume one from the other.

Symmetry with `entry_package_applied` (`trigger_price, stop_loss, take_profit, quantity, order_link_id, order_id`): the requested protection plus the concrete exchange orders that carry it. All order values come from ABI's response unchanged (exchange text, not normalized). There is no `order_link_id`: Bybit native protective children have an empty `orderLinkId` (ABI `nativeProtectionAttribution.ts`), ABI attributes them by `parentOrderLinkId` = the entry order's link id, already in `entry_package_applied` and `trade_cycle_opened`.

`take_order` is always present. When Engine's `take_price` is `null`, ABI keeps a far surrogate take order on the exchange (`nativeProtectionReconciliation.ts`, `computeSurrogateTakePrice`); the record shows that real order and its real trigger price next to `take_price: null` (owner decision 2026-10-19, option A). Two independent truths are kept: the strategy's wish (`take_price: null`) and what is actually on the exchange (`take_order`). The journal never hides or replaces either; marking such a take as technical is a later frontend concern. ABI behaviour is not changed.

`position_quantity` is the quantity of this trade cycle that both legs protect, not the whole physical position on the instrument (owner decision 2026-10-19).

### D6 ABI contract: `protection_orders`

ABI already holds both legs after every successful protection write: the read-back after amend (`reconciled`) or the initial read (`already_satisfied`), each with `orderId`, `triggerPrice`, `qty` (`AttachedProtectionLeg`); both legs carry the same `qty`, the cycle's current own filled position quantity. Today they are dropped before the response. The success body gains one required key:

```
protection_orders: {
  quantity,
  stop: { order_id, trigger_price },
  take: { order_id, trigger_price }
}
```

taken from the same read-back that proved the write; no extra exchange call. Runtime decoding is strict, like `abi-open-position-entry-order-identity-v1`: exact key sets, non-empty `order_id`, positive exact decimal text for `trigger_price` and `quantity`; anything else is `PositionManagementExecutionProtocolError`. Runtime does not compare these values to the command (ABI already proves the match before answering) and does not use them in any decision or persist them in state; `ProtectionAppliedConfirmation` carries them transiently to the journal. The existing echo check of `stop_price`/`take_price` stays. Old ABI bodies without the key are rejected, so Runtime and ABI are deployed together (same as Runtime #25 / ABI #24). The ABI side is `abi_executor_bot` change `abi-protection-orders-identity-v1`.

### D5 Ports and journal mechanics

- `OpenTradeEvaluationJournalPort` in `runtime/orchestrator/ports.py`; `ProtectionAppliedJournalPort` in `runtime/position_management_orchestrator/ports.py`. Both optional constructor arguments (`None` = no journaling), as the existing journal ports.
- `ProcessingJournalEventType.OPEN_TRADE_EVALUATED = "open_trade_evaluated"`, `PROTECTION_APPLIED = "protection_applied"`.
- `JsonlProcessingJournal` methods via `_record`: envelope schema version 2 with `strategy_instance_id`, best effort, a write failure never raises into orchestration and never changes state.
- `bootstrap/application.py` passes the JSONL journal into both.

## Risks / Trade-offs

- A protection confirmed by ABI but followed by a failed save is journaled, and the next bar repeats the Apply and journals it again: two records for one change. Same accepted behaviour as `entry_package_applied`. Readers take the latest record per cycle.
- Best-effort journal: a lost write loses one record; trading is unaffected.
- One `open_trade_evaluated` per bar per open position adds one line per bar per position to `runtime.jsonl`; size is small compared to `live_entry_evaluated`, which already runs every bar.
- Contract break: a Runtime deployed without the matching ABI fails every protection apply with a protocol error (position management stops moving stops). Mitigation: deploy both together, rollback both together.
- The audit document said "after ABI confirmation and save" for `protection_applied`; the code copy of `entry_package_applied` is "after confirmation, before save". This change follows the code.
