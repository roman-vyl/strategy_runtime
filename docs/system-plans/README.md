# Strategy Runtime system plans

This directory is the active architecture, state-design, and contract-planning
layer for Strategy Runtime.

The documents are intentionally layered:

1. [`runtime-master-plan.md`](runtime-master-plan.md) — highest-level
   architecture, implemented stopping point, open gates, and next sequence.
2. [`runtime-state-and-lifecycle-plan.md`](runtime-state-and-lifecycle-plan.md) —
   current state models plus the future lifecycle and persistence decisions.
3. [`runtime-contract-map.md`](runtime-contract-map.md) — exact implemented
   module-to-module request, response, identity, and projection seams.
4. [`runtime-abi-entry-reconciliation-master-plan.md`](runtime-abi-entry-reconciliation-master-plan.md)
   — approved but not yet implemented continuation from the Engine live-entry
   projection through ABI entry reconciliation and Runtime state updates.
5. [`overall-central-journal.md`](overall-central-journal.md) — deferred
   cross-service journal initiative outside the active Runtime sequence.

The documents explicitly distinguish:

- implemented and tested behavior;
- implemented domain boundaries not yet connected to production adapters;
- future state-transition behavior;
- open architecture gates.

Historical architecture packages are not an authority for current Runtime work.
When code advances the accepted boundary, these system plans must be updated in
the same change so implementation status does not drift again.
