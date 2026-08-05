# Tasks: Bounded Committed-Bar Intake v1

- [x] 1. Implement `CommittedBarIntakeBoundary`: bounded FIFO intake with
      `put_nowait`/`stop_accepting`/`get`/`task_done`, a linearized
      accept-lock, local capacity validation, and `IntakeNotAccepting` as
      a distinct exception from `queue.Full`.
- [x] 2. Implement `CommittedBarIntakeWorker`: atomic
      not_started/running/stopping/stopped state machine, one non-daemon
      consumer thread, race-free start/stop (including the start-vs-
      concurrent-stop race), and per-event failure isolation that keeps
      the worker alive.
- [x] 3. Wire the closed-bar webhook to enqueue via the boundary instead
      of `BackgroundTasks`, preserving existing validation/not-ready
      responses and distinguishing `queue_full`/`intake_stopping`
      rejections in server-side logs only.
- [x] 4. Wire production lifecycle in the composition root: construct the
      boundary and worker exactly once, wire the worker to the existing
      `CommittedBarOrchestrator`, sequence shutdown as stop-accepting →
      offloaded worker stop → outbound-client close, and keep
      startup-failure rollback leak-free (including when `start()`
      itself fails).
- [x] 5. Add `RUNTIME_COMMITTED_BAR_QUEUE_CAPACITY` configuration
      (required, positive integer, non-configurable worker count) and
      the canonical deployment example.
- [x] 6. Preserve first-fill's synchronous HTTP contract and the existing
      keyed-mutex registry unchanged; confirm same-instance serialization
      and different-instance non-blocking behavior still hold through the
      new intake worker call path.
- [x] 7. Verify the HTTP contract: acceptance, validation, not-ready,
      queue-full, and intake-stopping behavior, including the accept/
      stop-accepting linearization.
- [x] 8. Verify worker concurrency and lifecycle: FIFO ordering, at most
      one in-flight `process` call, the dequeue-vs-stop race in both
      directions, pending-event discard vs. in-flight completion at
      shutdown, event-loop-non-blocking shutdown, and no orphaned thread.
- [x] 9. Verify shared-writer serialization against the real
      `StrategyRuntimeOrchestrator` critical section (not just a
      mutex-holding stand-in) and duplicate-event idempotency through
      existing downstream reconciliation.
- [x] 10. Run repository-wide validation: focused and full test suites,
      lint/type checks, and `openspec validate --strict`.
