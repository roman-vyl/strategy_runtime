## 1. Orchestration Models

- [x] 1.1 Add immutable `CommittedBarEvent`.
- [x] 1.2 Add immutable `SelectedDeployment` and `StrategyBarProcessingUnit` containing no trace or processing context.
- [x] 1.3 Add validated per-unit outcome and aggregate result models.

## 2. Orchestration Ports

- [x] 2.1 Add `DeploymentCatalogPort`.
- [x] 2.2 Add `DeploymentSelectorPort` accepting only event and snapshot.
- [x] 2.3 Add `StrategyCycleDispatchPort`.
- [x] 2.4 Add semantic `ProcessingJournalPort` lifecycle methods.

## 3. Committed Bar Orchestrator

- [x] 3.1 Implement the exact catalog → selection → sorted dispatch sequence.
- [x] 3.2 Obtain catalog and selection exactly once per processing run.
- [x] 3.3 Create one immutable processing unit per selection.
- [x] 3.4 Sort by `strategy_instance_id` before dispatch.
- [x] 3.5 Isolate dispatch exceptions and continue remaining units.
- [x] 3.6 Fail closed on dispatcher outcome identity mismatch.
- [x] 3.7 Journal start, upstream failure, per-unit outcome, and completion.
- [x] 3.8 Raise typed preparation failure before fan-out.
- [x] 3.9 Return a validated aggregate result.

## 4. Strategy-Cycle Handoff

- [x] 4.1 Add terminal `StrategyCycleHandoffBoundary`.
- [x] 4.2 Return success without a sink.
- [x] 4.3 Forward the exact unit once when a sink is attached.
- [x] 4.4 Let sink exceptions cross the boundary for orchestrator isolation.
- [x] 4.5 Wire the handoff into the production composition root.

## 5. Verification

- [x] 5.1 Test exact call order and one-time upstream calls.
- [x] 5.2 Test zero, one, and multiple selected deployments.
- [x] 5.3 Test deterministic dispatch order.
- [x] 5.4 Test dispatch exception isolation.
- [x] 5.5 Test mismatched outcome identity.
- [x] 5.6 Test catalog and selection preparation failures.
- [x] 5.7 Test the exact processing-unit field set.
- [x] 5.8 Test terminal and sink-backed handoff behavior.
- [x] 5.9 Test the full production-composed utility contour.
- [x] 5.10 Run the complete Runtime verification suite.
- [x] 5.11 Validate the OpenSpec change strictly.
