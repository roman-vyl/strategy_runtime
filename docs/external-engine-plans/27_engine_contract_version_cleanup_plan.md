# Strategy Engine payload `contract_version` cleanup plan

Status: planned; Engine repository not modified from Strategy Runtime workspace.
Date: 2026-07-23

## Objective

Remove payload-level `contract_version` from Runtime-facing Strategy Engine
requests, responses, validation, OpenAPI models, and tests. Do not replace it
with another ID, hash, correlation field, or payload discriminator.

Transport compatibility shall be defined by the deployed endpoint and its
OpenAPI/schema version. The project has no compatibility requirement to accept two
incompatible payload schemas concurrently on one endpoint.

## Non-goals

- `strategy_version` was later removed by plan 29; this plan remains scoped to payload-level `contract_version`.
- Do not change endpoint paths unless the Engine audit shows endpoint versioning
  is already part of the intended public API design.
- Do not add a new `schema_version`, `api_version`, or equivalent body field.
- Do not modify Runtime as part of this Engine-side plan.

## Step 1 — Audit actual Engine usage

Search Engine source, OpenSpec, OpenAPI, serializers, validators, examples, and
tests for:

- `contract_version`;
- `unsupported_contract_version`;
- DTO discriminators or branches driven by the field;
- response echo assertions;
- diagnostics or receipts that persist it.

Classify every occurrence as request input, response output, validation,
branching, persistence, documentation, or historical material.

## Step 2 — Confirm no business calculation depends on it

Prove that strategy calculation, market-data loading, live-entry projection,
open-trade projection, and managed replay do not change based on
`contract_version`. If any branch exists solely to select old/new DTO shapes,
remove the obsolete branch rather than retaining the payload field.

## Step 3 — Update active Engine OpenSpec

For every active Runtime-facing Engine change/spec:

- remove `contract_version` from request requirements;
- remove it from response requirements and echo fields;
- remove missing/unsupported-version scenarios;
- state that one endpoint exposes one current schema;
- state that breaking contract changes are handled through endpoint/OpenAPI
  deployment, not through an in-body version selector.

Do not rewrite archived historical specifications unless the repository policy
requires archival consistency annotations.

## Step 4 — Remove request DTO fields

Delete `contract_version` from Runtime-facing Engine request/domain models,
including live-entry, open-trade, and any shared strategy-projection envelope.

Remove constructor arguments, parsing aliases, defaults, and fixtures.

## Step 5 — Remove response DTO fields

Delete `contract_version` from Engine result/domain models and HTTP response
models. Remove serialization and response echo logic.

## Step 6 — Remove validation and errors

Delete:

- required/non-empty validation for `contract_version`;
- accepted-version allowlists;
- `unsupported_contract_version` and equivalent error branches;
- error mappings and HTTP examples that exist only for this field.

Do not replace these checks with another payload-level version field.

## Step 7 — Remove internal propagation

Remove `contract_version` from application use-case arguments, adapter method
signatures, projection contexts, receipts, diagnostics, and internal result
objects. Internal calculations should receive typed objects matching the one
current schema.

## Step 8 — Update OpenAPI and examples

Remove the property from request/response schemas, required lists, examples,
and generated documentation. Verify strict models reject an extra removed
`contract_version` field if the API uses `extra=forbid` semantics.

## Step 9 — Update tests

Delete or rewrite tests for:

- missing `contract_version`;
- unsupported values;
- response echo;
- internal propagation.

Add contract tests proving:

1. valid requests without `contract_version` succeed;
2. responses do not contain it;
3. an extra `contract_version` from the removed payload shape is rejected when strict-extra validation
   is part of the API policy;
4. trading/projection results remain identical before and after cleanup for the
   same business inputs.

## Step 10 — Search-based closure

Run a repository-wide search. Remaining occurrences are permitted only in:

- archived historical documents clearly marked non-normative;
- migration notes explaining removal.

No active source, OpenSpec, OpenAPI, current documentation, or tests may require
or emit the field.

## Step 11 — Verification

Run the Engine repository's full verification suite, including formatter,
linter, type checker, unit tests, integration/API tests, OpenSpec strict
validation, and OpenAPI snapshot/generation checks.

## Definition of done

- Runtime-facing Engine request bodies do not contain `contract_version`.
- Runtime-facing Engine responses do not contain `contract_version`.
- Engine performs no validation, branching, persistence, or echo based on it.
- No replacement body-level version field is introduced.
- Removal of `strategy_version` is specified separately by plan 29.
- Active Engine specs, OpenAPI, docs, and tests describe one current schema per
  endpoint.
- Full Engine verification passes.
