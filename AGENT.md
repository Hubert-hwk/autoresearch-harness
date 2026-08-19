# AutoResearch Harness Agent Notes

This file captures the project intent and working agreements from the early
design conversation. Treat it as durable project memory for future agent work.

## Project Intent

This project is not an automatic paper-writing system and not a thin
`Claude Code + autoresearch skill` wrapper.

The goal is to engineer AutoResearch as a general harness for autonomous
business and engineering optimization loops. The harness should help an agent
propose optimization directions, validate them through bounded experiments,
manage branches and artifacts, evaluate model or business impact, preserve
memory, and decide what to do next.

The intended scenarios include:

- search, ads, and recommendation optimization
- prompt tuning and agent workflow tuning
- model parameter and serving configuration optimization
- strategy, rule, and product experiment optimization
- data pipeline and evaluation set improvement

The core value is the harness, not a single agent. Agents are planners,
proposers, critics, and analysts inside a larger auditable execution system.

## Target System Shape

The desired full loop is:

```text
Objective / Business Goal
  -> Context Collector
  -> Memory Manager
  -> Agent Research Planner
  -> Hypothesis / Trial Planner
  -> Branch / Workspace Manager
  -> Branch Lifecycle
  -> Mutation Protocol
  -> Trial Executor
  -> Effect Evaluator
  -> Decision Engine
  -> Artifact / Provenance Store
  -> Memory Update
```

The harness should eventually support:

- automatic optimization-direction proposal
- hypothesis generation with expected effects and risks
- branch creation per experiment direction
- code/config/prompt changes isolated per trial
- test, benchmark, offline eval, prompt eval, or model eval execution
- baseline-vs-candidate effect comparison
- guardrail and regression detection
- durable memory of successful patterns and repeated failures
- provenance from final recommendation back to trials, metrics, diffs, and logs
- accept/reject/retry/mutate/stop decisions

## Current MVP State

The initial implementation proves the smallest reusable protocol:

```text
TaskSpec -> Trial -> Executor -> Metrics -> Guardrails -> Analysis -> Report
```

Implemented modules:

- `models.py`: `TaskSpec`, `Trial`, `TrialResult`, `RunSummary`
- `spec.py`: JSON task loading
- `policy.py`: budgeted grid-style trial generation
- `evaluation.py`: metric and guardrail checks
- `runner.py`: run loop and artifact writing
- `analysis.py`: pass rate, failure reasons, and top trials
- `adapters/ranking_param_tuning.py`: search/ranking style parameter demo
- `adapters/prompt_tuning.py`: prompt tuning style demo
- `adapters/model_param_tuning.py`: model serving parameter tuning demo

Validation assets:

- `scripts/run-demo.ps1`
- `scripts/run-validation.ps1`
- `tests/test_mvp.py`
- examples for `ranking_param_tuning` and `prompt_tuning`

## Current Agentic Loop State

The project now includes a deterministic `v0.2` agentic research loop:

```text
TaskSpec
  -> baseline run
  -> analysis.json
  -> RuleBasedResearchAgent proposes Hypothesis
  -> BranchManager records experiment branch metadata
  -> focused candidate run
  -> EffectEvaluator compares baseline and candidate
  -> MemoryManager writes hypotheses, decisions, and lessons
  -> ResearchRegistry writes state, lifecycle events, and artifact index
```

Implemented modules:

- `hypothesis.py`: first-class `Hypothesis` and `TrialPlan`
- `agent.py`: deterministic rule-based research planner
- `branching.py`: branch metadata, lifecycle tracking, and optional branch
  creation
- `effect.py`: baseline-vs-candidate comparison
- `decision.py`: harness decision engine for accept/reject/retry/needs_review
- `memory.py`: JSONL-backed memory streams
- `memory_index.py`: relevance ranking for prior lessons before planning
- `mutation.py`: declarative mutation protocol for candidate task changes
- `agentic.py`: orchestration for the agentic research loop
- `llm.py`: provider-agnostic LLM client interface and OpenAI-compatible client
- `registry.py`: durable state, events, and artifact index for resumability
- `provenance.py`: JSONL evidence graph for artifact dependencies

Supported deterministic validation scenarios:

- search/ranking parameter tuning
- prompt tuning
- model serving parameter tuning
- NumPy BPR recommender tuning with real multi-seed training, top-k evaluation,
  model artifacts, training logs, and dataset fingerprints

The `research` command supports two agent modes:

- `--agent rule`: deterministic default planner used by tests and CI
- `--agent llm`: OpenAI-compatible LLM planner configured with environment
  variables such as `AUTORESEARCH_LLM_API_KEY`, `AUTORESEARCH_LLM_MODEL`, and
  `AUTORESEARCH_LLM_BASE_URL`

LLM output is constrained to a hypothesis and bounded candidate search space.
The harness still controls execution, metrics, guardrails, branch metadata,
memory, and final decisions.

Validation command:

```powershell
python -m autoresearch_harness research examples\prompt_tuning\task.json --branch-mode record
```

The loop currently uses `record` branch mode in validation, so it records the
experiment branch identity without switching the active worktree branch.

Agentic runs now write:

- `state.json`: current status, phase, run ids, recommendation, and task snapshot
- `events.jsonl`: ordered lifecycle events for interruption recovery
- `artifacts.jsonl`: evidence index pointing at task, trials, analysis, reports,
  hypothesis, branch metadata, effect, decision, and final result
- `provenance.jsonl`: dependency graph connecting decision evidence back to
  hypothesis, effect, baseline/candidate analysis, and trial artifacts
- `memory_context.json`: ranked prior lessons selected for the hypothesis step
- `branch_lifecycle.json`: experiment branch phase and disposition record
- `mutation_plan.json`: validated mutation manifest applied before candidate
  execution
- `mutation_artifact/candidate_task.json`: materialized candidate task used for
  candidate execution
- `mutation_artifact/mutation.diff`: git no-index diff between the baseline
  task and candidate task artifact

Memory retrieval is intentionally lightweight in this version. The
`MemoryManager` still stores append-only JSONL lessons, while
`memory_index.py` scores lessons against the current executor, baseline failure
reasons, guardrail metrics, primary metric, and search-space parameters. The
selected memory context is written as a first-class artifact before the agent
proposes a hypothesis, so later readers can inspect which prior knowledge was
available to the planner.

Mutation protocol is intentionally narrow in this version. The harness converts
the agent hypothesis into `mutation_plan.json`, validates that candidate
search-space values remain within the original task contract, records the
operations, and derives the candidate task from that manifest. This gives the
system a stable place to later add prompt patches, config patches, code diffs,
and branch commits without letting free-form agent output directly mutate the
workspace.
The current implementation also materializes the mutation into
`mutation_artifact/candidate_task.json` and captures
`mutation_artifact/mutation.diff` with `git diff --no-index`. Candidate
execution reloads the materialized task artifact rather than relying on an
in-memory mutated object.

Branch lifecycle is now explicit but still conservative. `branch.json` records
base branch, base commit, experiment branch, mode, and whether a branch was
created. `branch_lifecycle.json` records `branch_prepared`,
`mutation_attached`, `candidate_executed`, and `decision_recorded`, then assigns
a disposition such as `record_only`, `retain_for_promotion`,
`retain_for_review`, `retain_for_retry`, or `retain_for_audit`.

Use `python -m autoresearch_harness status --research-id <id>` to inspect a
previous run. Use `python -m autoresearch_harness resume --research-id <id>` to
continue from the last completed phase. The current resume implementation can
reuse completed baseline, hypothesis, branch, and candidate artifacts.

Decision semantics are intentionally separate from effect metrics:

- `effect.json` stores metric comparison only
- `decision.json` stores the harness recommendation, confidence, reasons,
  blocking guardrails, and next action
- `state.json.decision_evidence` stores a compact evidence chain for the final
  decision, while `provenance.jsonl` stores the full graph

Current Git state:

- local git repository exists on `main`
- GitHub remote exists: `https://github.com/Hubert-hwk/autoresearch-harness`
- GitHub Actions CI runs compile and unit-test validation

## v0.3 Implementation Update

The August 2026 literature review selected an auditable empirical software
optimization engine as the next system direction. See `ROADMAP_V03.md` and
`research/RESEARCH_DIRECTION_2026.md`.

Phase 1 of v0.3 now provides a versioned `task.v2` contract and an
`external_command` executor. It executes trusted command arrays without shell
interpolation, applies per-trial timeouts, parses machine-readable metrics, and
records stdout, stderr, execution manifests, declared artifacts, and hashes.
Existing `task.v1` examples remain compatible.

Phase 2 adds a task-declared editable-path policy, the typed `patch.v1`
protocol, and `patch-run`. Patch candidates run in detached Git worktrees tied
to a resolved base commit without switching the active branch. Validation is
atomic, path and size constrained, and limited to UTF-8 `replace_text` plus
opt-in `create_file`. Pre/post evaluation audits reject any changed path or
file hash not explained by the patch. Workspaces and failure evidence are
retained for inspection. This is source-worktree isolation, not an OS security
sandbox.

Phase 3 adds `experiment_graph.py`. Its append-only, SHA-256 hash-chained event
stream is the durable source for frozen `ExperimentNode` views. Rebuild checks
event order, ids, graph identity, hashes, parent availability, and lifecycle
transitions. Nodes retain lineage, hypotheses, mutations, base commits,
workspaces, fidelity, consumed budget, evaluations, feedback, decisions, and
artifact references. `patch-run` records its lifecycle automatically and can
join a shared graph with explicit parent nodes. `graph-status` validates and
rebuilds the derived graph snapshot. The graph is currently single-writer;
the adaptive scheduler uses it sequentially, and writer coordination remains a
future execution-backend milestone.

Phase 4 adds `scheduling.v1` and `adaptive-run`. Initial candidates are sampled
without replacement from finite grid positions using a fixed seed. Successive
Halving promotes guardrail-passing candidates by the primary objective while a
direction-aware Pareto archive retains nondominated results at each fidelity.
Global trial, cumulative-fidelity, and wall-time budgets are checked before
every evaluation; external subprocess timeouts are clipped to remaining wall
time. Every fidelity observation is an experiment node, with promoted
higher-fidelity observations pointing to lower-fidelity parents. Unexpected
executor exceptions are stored as failed trial evidence. The Phase 4 review
and residual limitations are in `reviews/PHASE4_REVIEW_2026-08-19.md`.

Phase 5 adds `verification.v1`, `fingerprint.v1`, `replay.v1`, `verify-run`, and
`replay`. Verification executes alternating baseline/candidate order over
paired seeds and uses deterministic bootstrap confidence intervals. Promotion
requires complete pairs, a confidence lower bound above the declared effect
floor, candidate guardrail compliance, and stable fingerprints. Fingerprints
cover the semantic task, dataset, evaluator dependencies, harness source,
Python/packages, selected runtime settings, platform, and Git state. Replay
manifests are content-hashed; default replay blocks on drift, compares declared
scientific metrics within tolerance, observes global budgets, and detects
fingerprint changes during execution. Review details are in
`reviews/PHASE5_REVIEW_2026-08-19.md`.

Phase 6 adds `evidence-memory.v1` and the `memory-ingest`, `memory-query`,
`memory-status`, and `memory-invalidate` commands. Durable claims require a
complete verification and matched replay, retain copied evidence bundles, and
carry typed effects, applicability scope, validity, and supersession metadata.
The event log is append-only and hash-chained; queries revalidate evidence and
exclude inactive, expired, corrupted, or out-of-scope claims. The agentic
planner consumes matching evidence memory without treating legacy exploratory
lessons as verified facts. Review details are in
`reviews/PHASE6_REVIEW_2026-08-19.md`.

## Gap To Desired System

The current project is a validated prototype, but it is still short of the
intended applied AutoResearch harness.

Missing major capabilities:

- richer provider-specific LLM clients and prompt templates
- structural syntax-aware code patches and binary mutations
- OS/container sandboxing for untrusted command-backed experiments
- asynchronous/concurrent scheduling and coordinated multi-writer graph access
- advanced sequential tests, multiple-comparison correction, and BCa intervals
- signed provenance and remote attestation for replay evidence
- stronger resume safety checks beyond the existing execution fingerprints
- release discipline and richer documentation

## Next Engineering Milestone

Stabilize and package the completed `v0.3 Applied Research Execution Core`.

Implementation order:

1. Add cross-process writer coordination for event stores.
2. Add signed provenance or remote attestation where trust boundaries require it.
3. Strengthen sequential statistics and multiple-comparison control.
4. Add OS/container isolation for untrusted evaluators.
5. Establish release, migration, and compatibility discipline.

This should be implemented incrementally, with each step validated locally and
pushed after tests pass.

## Engineering Principles

- After every development session, write a local Markdown log under
  `dev-logs/` covering date, background, what happened, what changed, and the
  observed effect. The directory is intentionally Git-ignored and must not be
  included in commits or pushes.
- Keep the harness generic; avoid baking one business scenario into the core.
- Put scenario-specific behavior behind adapters.
- Preserve traceability for every recommendation.
- Treat failures as first-class learning signals, not just failed runs.
- Prefer a working deterministic loop before adding LLM calls.
- Make artifacts readable and replayable before building UI or dashboards.
- Do not let the project regress into a simple parameter sweep tool.
