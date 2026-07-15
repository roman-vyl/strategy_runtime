# Cross-Repository Implementation Gates

This document records mandatory gates that must be resolved before the corresponding Strategy Runtime behaviour is implemented.

The purpose of these gates is to keep responsibilities auditable across repositories. When a gate is reached, work moves to the owning repository. That repository must receive an OpenSpec change describing the required behaviour, design decisions, implementation tasks, verification, and closure evidence. Strategy Runtime implementation may continue only after that neighbouring change is designed, approved, implemented, and verified.

## Gate 01 — Strategy Engine runtime contract adaptation

Status: mandatory; already identified.

Before Strategy Runtime implementation, Strategy Engine must expose an approved runtime-facing request and neutral current-point decision contract. See `api-and-data-structure-audit.md`.

## Gate 02 — ABI per-bar reconciliation and execution lifecycle audit

Status: mandatory before finalising Runtime-to-ABI delivery semantics.

The ABI Executor source must be audited at code level. The audit must establish, with references to concrete code and tests:

- how ABI accepts a signal from Strategy Runtime;
- what response means that ABI has accepted responsibility for the signal;
- how ABI constructs and places exchange orders;
- how ABI distinguishes terminal rejection from a recoverable exchange failure;
- how and when ABI retries exchange interaction;
- how ABI confirms that an order was actually created or otherwise reached the intended exchange state;
- how ABI records journal/state transitions;
- how ABI handles duplicate signal delivery;
- how ABI restores pending work and exchange reconciliation after restart;
- whether ABI accepts one complete current-point result for every permitted strategy instance on every base-stream bar;
- whether the current `/signals` endpoint is an imperative create-order command or a declaration of desired strategy state;
- how ABI recognises a semantically unchanged result and treats it as a no-op;
- how ABI replaces, cancels, or preserves pending entries when the newly supplied result differs;
- how ABI reconciles allowed stop-loss, take-profit, or other protection changes for an already open position;
- how repeated transport delivery is distinguished from a new-bar result;
- how ABI calculates quantity;
- how ABI scopes pending entry orders to a runtime strategy instance or equivalent owner.

Agreed responsibility boundary:

> Once ABI confirms that it has accepted the per-bar strategy result, Strategy Runtime considers its responsibility for that handoff complete. ABI then owns semantic deduplication, desired-versus-actual reconciliation, exchange execution, retries, and lifecycle recovery. Exchange availability, retries, confirmation, reconciliation, and restart recovery belong to ABI Executor.

When this gate is reached, the ABI repository must receive an OpenSpec change documenting any required contract or implementation changes. No Runtime retry, ledger, or completion model may be finalised before the audit is complete.

## Gate 03 — MDS stream-state transition webhook

Status: mandatory before implementing live suspension safety.

Market Data Service must provide a semantic notification when a stream transitions from `ready` to any other state. The event must identify which stream lost readiness.

Conceptual event:

```text
stream identity
previous state = ready
new state = any non-ready state
```

The exact endpoint, payload, delivery policy, and MDS implementation are not yet designed.

When this gate is reached, work must move to the Market Data Service repository. An OpenSpec change must be created there to:

1. audit the current stream-state transition points;
2. design the outbound notification contract;
3. guarantee notification on every `ready -> non-ready` transition;
4. define delivery and failure semantics;
5. implement and verify the change;
6. include all MDS changes in the cumulative MDS patch.

## Gate 04 — Runtime suspension and ABI scoped cancellation

Status: mandatory after Gate 03 and the ABI audit.

When Strategy Runtime receives a `ready -> non-ready` event for one stream, it must not stop the entire service. In v1, it suspends only active strategy instances whose explicitly configured base stream matches that stream. Runtime does not yet discover non-base dependencies from the spec.

For every affected instance, Runtime must instruct ABI to cancel pending orders that are not associated with an already open position.

The safety boundary is:

```text
cancel:
    pending entry orders and other unfilled orders intended to create a new position

preserve:
    open positions
    stop-loss protection for open positions
    take-profit protection for open positions
    other position-linked protective orders
```

The exact cancellation scope and ABI request contract are not yet approved. The absence of a Runtime reaction to non-base stream failure is an accepted v1 gap and is not solved by this gate. They depend on the ABI source audit, including how ABI associates orders with strategy/runtime instances and distinguishes entry orders from protection.

When this gate is reached, the ABI repository must receive an OpenSpec change for any required scoped-cancel contract and implementation. Runtime must not invent a competing order classification.

## Future review — non-base stream dependency safety

Status: explicitly deferred beyond v1.

Runtime v1 binds each active spec only to the supplied `ticker + timeframe` base stream. It does not derive, receive, or index additional streams used internally by Strategy Engine. Consequently, a non-base stream leaving `ready` does not automatically suspend the strategy.

Before multi-stream safety coverage is introduced, this architecture must be revisited and an explicit contract designed for communicating or deriving complete stream dependencies. No runtime manifest or spec inspection mechanism is approved today.

## Gate 05 — Recovery after stream returns to ready

Status: mandatory design review after Gates 03 and 04.

The transition from non-ready back to `ready` must be audited and explicitly designed before automatic runtime resumption is implemented.

Open questions include:

- whether affected runtime strategy instances resume immediately or only on the next base-stream closed-bar webhook;
- whether any additional readiness observation is required;
- whether previously cancelled entry intents remain terminal;
- whether any reconciliation with ABI is required before resumption;
- how repeated state transitions are ordered and deduplicated.

No automatic recovery behaviour is approved yet. This gate must be revisited with evidence from the implemented MDS transition contract and the audited ABI lifecycle.

## Agreed gate workflow

```text
Strategy Runtime design reaches a cross-repository dependency
        |
        v
open the owning neighbouring repository
        |
        v
create an OpenSpec change with audit, design, tasks, tests, and closure criteria
        |
        v
approve the design
        |
        v
implement and verify in the owning repository
        |
        v
return to Strategy Runtime and continue the blocked design/implementation
```

## Gate 06 — Independent strategy configurator and validator

Status: mandatory before Runtime is expected to accept arbitrary operator-authored specs safely as a product capability; explicitly deferred for the initial end-to-end smoke test.

Runtime v1 has no independent configurator or authoritative semantic validator. The smoke-test stage relies on strategy files produced and validated by the existing Workbench/frontend or CLI authoring path.

Before general-purpose production onboarding of specs is approved, the existing authoring and validation code must be audited to determine:

- where canonical strategy construction currently lives;
- where structural and semantic validation currently live;
- whether Workbench, Research Service, CLI, or shared legacy code is authoritative;
- which validation logic must be extracted into a standalone reusable module or service;
- how validation errors are versioned and returned;
- whether Runtime validates at discovery time, activation time, or through a separate control-plane workflow;
- how the validator stays contract-compatible with Strategy Engine.

When this gate is reached, the owning repository or new standalone repository must receive an OpenSpec change covering audit, extraction design, API or library contract, tests, migration, and closure evidence. Runtime must not duplicate an ad hoc subset of the validator before this gate is resolved.

Until then, the documented safety assumption is:

> The operator places only previously constructed and validated strategy files into the Runtime spec directory. Runtime may surface parse or Engine-evaluation failures, but it does not certify semantic correctness.
