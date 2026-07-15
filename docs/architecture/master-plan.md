# Architecture Master Plan

This document records future system-level work that spans multiple repositories but is not yet an active OpenSpec implementation gate.

## Overall Central Journal

Create a standalone **Overall Central Journal** for the financially responsible live trading path.

The participating modules are:

- Market Data Service;
- Strategy Runtime;
- Strategy Engine;
- ABI Executor.

Each module must emit typed, timestamped, object-oriented events within its own responsibility boundary, using compatible correlation semantics so one live flow can be reconstructed across service seams. The Central Journal will receive, store, order, filter, correlate, and present those events as trading and technical views.

Backtest-only modules, including Research Service, are outside this integration scope because they do not own live financial decisions or exchange execution.

The current local JSONL journal in Strategy Runtime is the first implementation of this shared event model. Equivalent semantics must later be introduced into MDS, Strategy Engine, and ABI Executor before they are connected to the Overall Central Journal.

This master-plan item remains open until the standalone journal module and all listed live-module integrations are designed, implemented, and verified.
