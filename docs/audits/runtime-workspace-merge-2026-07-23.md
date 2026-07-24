# Runtime workspace merge — 2026-07-23

## Purpose

Consolidate the complete Strategy Runtime codebase with the later documentation and OpenSpec-only edits that had been written into a reduced workspace copy.

## Merge direction

- Base: complete Runtime repository from `strategy-runtime-spec-hash-boundary-cleanup.zip`.
- Overlay: files present in the reduced `strategy_runtime_cleaned` workspace.
- Policy: overlay files were copied without deleting any base file.

## Conflict resolved

The reduced workspace contained an obsolete integration test importing the removed pre-vertical-refactor module path `strategy_runtime.application`. The complete repository version of that test was retained because it targets the current vertical utility structure.

## Verification

- `PYTHONPATH=src pytest -q` → `79 passed`
- `python -m compileall -q src tests` → passed

## Canonical workspace

`/mnt/data/runtime_stage1_audit/strategy_runtime_main`

A synchronized compatibility copy is also maintained at:

`/mnt/data/runtime_stage1_audit/strategy_runtime_cleaned`
