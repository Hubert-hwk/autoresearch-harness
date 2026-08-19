# Phase 5 Stage Review

Date: 2026-08-19

## Review scope

Repeated-seed execution, statistical effect claims, independent promotion
gates, fingerprints, manifest integrity, replay drift behavior, global budgets,
failure evidence, task round-trips, and compatibility with Phases 1–4.

## Findings resolved during the phase

### High: prior decision confidence was heuristic

Earlier decisions used fixed confidence constants or adapter-specific standard
deviations. Verification now uses paired seed differences and a deterministic
bootstrap interval whose declared coverage and samples are preserved.

### High: no joint execution fingerprint

Task, data, evaluator, harness, environment, dependencies, platform, and Git
state could change independently. `fingerprint.v1` now combines these sources,
including explicit evaluator dependency paths.

### High: replay could execute after silent drift

Replay now blocks before trials when fingerprints differ. Diagnostic
`--allow-drift` remains explicit and does not suppress mismatch evidence.
Fingerprinting runs again afterward to detect evaluator mutation during replay.

### High: replay manifest could be modified silently

The manifest now includes a canonical SHA-256 content hash. Changes to expected
metrics, parameters, fingerprints, or task references fail before execution.

### Medium: semantic JSON numbers caused false drift

A task constructed with `10` could reload as `10.0` and receive a different
hash. Fingerprint input now normalizes semantically equal JSON numbers.

### Medium: volatile timing metrics made exact replay unreliable

Replay metrics are now explicitly declared. Scientific metrics can use strict
tolerance while wall/evaluation timing remains enforced through guardrail
status and budgets rather than byte-for-byte equality.

### Medium: replay did not apply the global wall boundary

Replay now checks trial and wall budgets before each execution and clips
external command timeout to remaining wall time.

## Verified behavior

- Alternating execution order still reconstructs correct seed pairs.
- Bootstrap output is deterministic for a fixed bootstrap seed.
- A positive stable effect passes all independent gates.
- A superior primary metric with guardrail failures is rejected.
- Clean replay matches all declared metrics and guardrail statuses.
- Evaluator changes block replay without running trials.
- Allowing drift runs diagnostically and exposes metric mismatches.
- Manifest tampering is rejected by its content hash.
- Existing task, adaptive, graph, patch, and agentic tests remain compatible.

## Residual limitations accepted for this phase

- Percentile bootstrap is intentionally simple; BCa intervals and sequential
  testing are not implemented.
- A content hash provides integrity detection, not an external signature or
  trusted timestamp.
- The harness passes and records seeds but cannot prove that an evaluator uses
  them meaningfully.
- Only a safe allowlist of ambient environment variables is fingerprinted to
  avoid persisting secrets; undeclared environment dependencies remain a task
  authoring risk.
- Hardware fingerprinting is host-level and does not yet include detailed GPU
  driver or accelerator topology.

## Review decision

Phase 5 meets the verification and replay exit gate. Phase 6 should consume
these statistically gated, fingerprinted outcomes rather than deriving memory
from exploratory point estimates.
