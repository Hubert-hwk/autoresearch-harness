# v0.3 Applied Research Execution Core

This roadmap converts the August 2026 literature review into incremental,
testable engineering work. The north star is an auditable empirical software
optimization engine, not an automatic paper writer.

## Release outcome

Given a versioned, scorable task, the harness should be able to create isolated
code/config/prompt candidates, execute declared evaluators under explicit
budgets, explore related candidates, and replay the evidence supporting a
promotion decision.

## Delivery plan

| Phase | Deliverable | Exit gate | Status |
|---|---|---|---|
| 0 | Research baseline and architecture decision | Primary-source review and accepted direction | Complete |
| 1 | Real execution contract | Command-backed task produces metrics, logs, hashes, artifacts, timeout evidence | Complete |
| 2 | Patch mutation and isolation | Candidate runs in a disposable worktree without switching the user's branch | Complete |
| 3 | Experiment graph | Immutable nodes preserve parentage, mutation, feedback, cost, and status | Complete |
| 4 | Adaptive scheduling | Random baseline, successive halving, and Pareto archive obey global budgets | Complete |
| 5 | Verification and replay | Repeated seeds, confidence, fingerprints, independent gates, `replay` command | Complete |
| 6 | Evidence memory | Typed causal lessons with validity and supersession links | Complete |

## Phase 1 contract

`task.v2` adds an optional command execution block and wall-time budget while
remaining compatible with existing `task.v1` examples. `external_command`
tasks declare:

- a command argument array; no shell interpolation is used;
- a working directory;
- a per-trial timeout;
- a metrics JSON path inside the trial output directory;
- additional expected artifact paths;
- non-reserved environment variables.

The harness provides each evaluator with:

- `AUTORESEARCH_TRIAL_ID`;
- `AUTORESEARCH_TRIAL_PARAMS`;
- `AUTORESEARCH_OUTPUT_DIR`;
- `AUTORESEARCH_TASK_NAME`;
- `AUTORESEARCH_DATASET`, when configured.

Every trial records resolved parameters, stdout, stderr, parsed metrics, an
execution manifest, declared artifacts, SHA-256 digests, sizes, status, exit
code, and duration. Invalid metrics, missing artifacts, non-zero exits, and
timeouts are failed trial evidence rather than fatal run errors.

The command runner is not yet a security sandbox. A task file is executable
configuration and must be trusted. Filesystem/process isolation is the central
deliverable of Phase 2.

## Phase 2 contract

`task.v2` can now declare a mutation allowlist with `editable_paths`,
`allow_create`, and `max_file_bytes`. A separate `patch.v1` manifest supports
two bounded UTF-8 text operations: exact-count `replace_text` and opt-in
`create_file`.

`patch-run` resolves a base commit, creates a detached Git worktree, applies the
entire patch atomically after validation, remaps the command-backed task into
that worktree, and runs the evaluator. It never switches the source worktree's
branch. Before and after evaluation it verifies that Git's changed-path set and
file hashes exactly match the patch application. Undeclared evaluator side
effects fail the experiment.

Each patch experiment preserves:

- the requested patch and resolved task snapshot;
- base commit, source branch, and detached workspace identity;
- unified diff and before/after file hashes;
- pre-run and post-run workspace audits;
- candidate metrics, logs, artifacts, and final state.

Workspaces are deliberately retained on success and failure. Removal is an
explicit API operation; automatic retention policy is deferred until promotion
semantics are defined. The evaluator remains trusted executable code: worktree
isolation protects the source checkout from declared mutations, but is not an
OS security sandbox.

## Phase 3 node contract

The stable unit of research is now a frozen `ExperimentNode` view:

```text
id, parent_ids, hypothesis, mutation, base_commit
workspace, fidelity, budget_spent, status
evaluation_bundle, decision, artifact_refs
```

Node events will be append-only. Aggregate views may be rebuilt from events so
that interruption recovery does not depend on partially updated summary files.

`experiment_events.jsonl` is the source of truth. Every event includes a
monotonic sequence, unique event id, previous-event hash, and SHA-256 content
hash. Rebuild rejects gaps, duplicate ids, graph mismatches, modified content,
or a broken hash chain. `experiment_graph.json` is only a replaceable derived
view.

The implemented lifecycle is:

```text
planned -> workspace_prepared -> running -> evaluated
                                      |          |
                                      v          v
                                    failed    accepted / rejected / needs_review
```

Events attach evaluation bundles, feedback, consumed budget, decisions, and
artifact references without rewriting earlier records. Parent nodes must exist
before children are created, which gives deterministic topological rebuild and
prevents dangling lineage.

Each `patch-run` creates an experiment node automatically. Multiple runs can
join a shared graph through `--graph-dir`, `--node-id`, and repeated
`--parent-node` arguments. `graph-status` validates the event chain and rebuilds
the current node view. The current store assumes a single writer; scheduling
uses that mode sequentially, while concurrent-writer coordination remains a
future execution-backend milestone.

## Phase 4 scheduling contract

`task.v2` can now declare a `scheduling.v1` block with a fidelity parameter,
strictly increasing positive fidelity levels, initial candidate count,
reduction factor, deterministic random seed, and maximize/minimize Pareto
objectives.

`adaptive-run` performs the following bounded loop:

1. Sample unique grid positions with a seeded random baseline instead of taking
   a biased prefix of the Cartesian product.
2. Evaluate active candidates at the current fidelity.
3. Reject guardrail failures, rank eligible candidates by the primary metric,
   and promote `max(1, floor(n / reduction_factor))` candidates.
4. Build a nondominated Pareto archive for every fidelity stage.
5. Represent higher-fidelity evaluations as child nodes of promoted
   lower-fidelity observations in the experiment graph.

Global limits cover trial count, wall time, and cumulative fidelity units.
Trial and fidelity limits are checked before every evaluation. For external
commands, the process timeout is clipped to the remaining global wall budget;
in-process adapters are checked cooperatively at trial boundaries. Unexpected
executor exceptions become failed trial evidence instead of leaving graph
nodes in `running`.

The scheduler writes `adaptive_trials.jsonl`, `schedule_events.jsonl`,
`pareto_archive.json`, the experiment event/graph files, incremental state, a
final result, and a report. Its review is recorded in
`reviews/PHASE4_REVIEW_2026-08-19.md`.

## Phase 5 verification contract

`verification.v1` declares a seed parameter, unique repeated seeds, confidence
level, deterministic bootstrap configuration, minimum primary improvement,
candidate guardrail pass-rate gate, replay tolerance, scientific replay
metrics, and additional evaluator dependency paths to fingerprint.

`verify-run` alternates baseline/candidate execution order across seeds, derives
positive-is-better paired improvements, and computes a deterministic percentile
bootstrap confidence interval. Promotion is independent from adaptive search
and requires all of the following:

- every declared seed produces a complete baseline/candidate primary pair;
- the confidence interval lower bound clears the minimum improvement;
- candidate guardrail pass rate clears its declared threshold;
- the execution fingerprint remains unchanged during verification.

`fingerprint.v1` covers the semantic task contract, dataset, command-line and
explicit evaluator dependency files, harness Python sources, interpreter,
selected non-secret runtime variables, installed package versions, platform,
and Git commit/dirty state. Semantically equal JSON numbers such as `10` and
`10.0` normalize to the same fingerprint.

`replay.v1` preserves exact trial parameters and expected scientific metrics.
The manifest has its own content hash. `replay` blocks before execution on
fingerprint drift unless `--allow-drift` is explicit, observes global trial and
wall budgets, compares declared metrics within tolerance, checks guardrail
status, and fingerprints again after execution to detect evaluator mutation.

The Phase 5 review is in `reviews/PHASE5_REVIEW_2026-08-19.md`.

## Phase 6 evidence-memory contract

`evidence-memory.v1` separates durable, verification-backed knowledge from the
older exploratory `lessons.jsonl` records. A memory can only be ingested from a
complete Phase 5 verification and a matched replay with stable fingerprints,
valid self-hashes, and a matching replay-manifest hash.

Each record contains a typed effect claim, changed parameters, paired interval,
guardrail outcome, task/executor/metric/data/evaluator applicability scope,
durable copied evidence references, and validity metadata. Claims are one of
`beneficial_effect`, `guardrail_tradeoff`, `harmful_or_null_effect`, or
`inconclusive_effect`.

`evidence_memory_events.jsonl` is the append-only source of truth. Its event
sequence and SHA-256 hash chain detect modification, while the replaceable
`evidence_memory.json` snapshot is rebuilt from events. Conflicting active
claims require explicit supersession. Records can also be invalidated, and
queries exclude inactive, expired, scope-incompatible, or corrupted evidence.

The agentic planner consumes only active, integrity-checked evidence memories
that match the current execution scope. Legacy lessons remain available as
exploratory hints and are not upgraded to verified claims implicitly.

The Phase 6 review is in `reviews/PHASE6_REVIEW_2026-08-19.md`.

## Quality gates for every phase

- Existing deterministic examples remain compatible.
- New failure paths have tests, not only success paths.
- Runs never silently discard failed or dominated attempts.
- Serialized tasks round-trip without losing metric or guardrail semantics.
- Global and per-trial budgets are enforced and reported.
- User worktree changes are preserved.
- Documentation distinguishes implemented isolation from planned isolation.

The evidence and detailed rationale for this roadmap are in
[`research/RESEARCH_DIRECTION_2026.md`](research/RESEARCH_DIRECTION_2026.md).
