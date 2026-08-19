# Phase 6 Review — Evidence Memory

## Scope

This review covers verified-memory ingestion, durable evidence retention,
append-only lifecycle events, applicability queries, conflict handling, planner
integration, CLI behavior, and regression safety.

## Findings resolved

### High — exploratory lessons could be mistaken for durable evidence

The existing `lessons.jsonl` path accepted observations from ordinary agentic
runs without repeated verification or replay. Phase 6 introduces a separate
`evidence-memory.v1` store. Ingestion now requires complete paired verification,
a matched replay, stable fingerprints, and consistent artifact hashes. Legacy
lessons remain explicitly exploratory.

### High — source run cleanup could orphan memory evidence

Initial records pointed back to verification and replay run directories. The
ingestion path now copies the verification result, replay result, manifest,
task, parameter sets, and before/after fingerprints into a durable per-memory
evidence bundle. Queries revalidate the archived hashes.

### High — contradictory claims could coexist as active knowledge

Claims with the same scope and parameter change but opposing effect classes now
require an explicit `supersedes` relationship. Supersession is recorded in the
same append-only event that creates the replacement, so rebuild cannot observe
a half-applied transition. Explicit invalidation is also append-only.

### High — evidence or event tampering was not detected

Verification and replay results have self-content hashes. The memory event log
has monotonic sequence numbers, unique event ids, previous-event hashes, and
event content hashes. Query-time evidence validation excludes modified or
missing bundles.

### Medium — verified evidence was not connected to planning

The agentic hypothesis stage now queries scope-compatible active evidence and
records the selected memory ids in `memory_context.json`. Exploratory and
verified records can both inform planning, while the context preserves their
different provenance.

### Medium — repeated identifiers could hide different content

Idempotent ingestion previously returned an existing id without checking the
new content. It now compares the stable claim, scope, and evidence identity and
rejects collisions. Ingestion performs this validation before copying evidence,
which avoids overwriting an existing bundle or leaving a bundle for a rejected
conflict.

### Medium — malformed validity timestamps could break queries

New records and rebuilt event payloads now require timezone-aware ISO
timestamps. Query limits must be positive, and expiry comparisons are safe.

### Medium — verification budget validation blocked saved task reloads

The load-time coupling between verification seed count and exploratory trial
budget made narrowed agentic task snapshots unreadable. Verification still
enforces its exact run budget at execution time, while general task loading no
longer rejects an otherwise valid saved task.

## Validation

- `git diff --check`
- Python bytecode compilation for `src` and `tests`
- 43 unit/integration tests, including real external-command verification and
  replay in the evidence-memory lifecycle tests
- Negative coverage for unmatched replay, evidence tampering, event tampering,
  scope mismatch, conflicting claims, identifier collision, invalid timestamps,
  supersession, and invalidation

## Residual limitations

- SHA-256 integrity is not an identity signature or remote attestation.
- The event store assumes one writer; concurrent processes need locking or a
  transactional backend.
- Applicability is deliberately conservative and uses exact executor, metric,
  dataset, and evaluator-dependency matching rather than a learned ontology.
- Conflict detection is exact for scope and changed parameters; semantically
  related but structurally different interventions need human review.
- A verified paired effect supports a claim within the recorded evaluator scope;
  it does not establish unrestricted real-world causality.

## Review outcome

Phase 6 meets its roadmap exit gate. The seven-phase v0.3 execution-core plan is
feature-complete and should move to stabilization rather than adding another
core phase immediately.
