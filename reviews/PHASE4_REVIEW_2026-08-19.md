# Phase 4 Stage Review

Date: 2026-08-19

## Review scope

This review covers candidate generation, global budgets, multi-fidelity
promotion, Pareto semantics, experiment-graph integration, executor failures,
serialized task compatibility, CLI behavior, and evidence artifacts.

## Findings resolved during the phase

### High: grid-prefix bias under small budgets

The original runner enumerated the Cartesian product in declaration order and
stopped at `max_trials`. Small budgets therefore explored only a systematic
prefix. `adaptive-run` now samples unique product indices without replacement
using a task-declared seed, without materializing the full product.

### High: external commands could exceed remaining wall budget

The original wall limit was checked only before a trial. The external executor
now accepts a per-call timeout override, and the adaptive scheduler clips it to
remaining global wall time. Trial and cumulative-fidelity limits are also
checked before every evaluation.

### High: executor exceptions left no scheduler evidence

An unexpected in-process adapter exception could abort orchestration while an
experiment node remained `running`. The scheduler now converts the exception
into a guardrail-failing `TrialResult`, records it in JSONL and the experiment
graph, and lets the stage reach a deterministic decision.

### High: non-finite budgets could bypass comparisons

`NaN` and infinity can make ordinary comparisons ineffective. Task parsing and
the runtime entry point now reject non-finite or non-positive wall budgets,
fidelity budgets, and fidelity levels.

### Medium: missing primary metrics could fail final selection

Pareto and promotion paths filtered missing objectives, but final best
selection could still index an absent primary metric. It now skips incomplete
results while retaining them as negative evidence.

### Medium: tie ordering was unintentionally reversed

Reverse sorting a `(metric, candidate_id)` tuple caused equal maximize scores to
prefer lexically later candidates. Promotion now uses stable metric-only
sorting, preserving seeded candidate order for ties.

## Verified behavior

- Seeded candidate sampling is deterministic and contains no duplicates.
- Successive Halving creates correct higher-fidelity parent links.
- Guardrail failures are not promoted or admitted to the Pareto archive.
- Pareto dominance respects independent maximize and minimize directions.
- Trial, cumulative-fidelity, and external wall-time limits stop scheduling.
- Task serialization round-trips scheduling and budget contracts.
- Existing non-adaptive runs and earlier experiment workflows remain valid.

## Residual limitations accepted for this phase

- In-process Python adapters cannot be forcibly preempted; wall time is enforced
  cooperatively between trials. Hard isolation belongs to a later sandbox
  milestone.
- The experiment graph remains single-writer. Concurrent scheduler workers need
  a lock or transactional event backend before parallel execution.
- Fidelity stages rerun candidates from scratch; checkpoint continuation is not
  yet part of the executor protocol.
- Pareto values are point estimates. Repeated seeds, confidence intervals,
  evaluator fingerprints, and independent promotion gates belong to Phase 5.

## Review decision

Phase 4 meets its exit gate for deterministic sequential scheduling. Phase 5
should begin with reproducibility fingerprints and repeated-seed verification
before adding parallel workers.
