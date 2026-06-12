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
- NumPy BPR recommender tuning with real training and top-k evaluation

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

## Gap To Desired System

The current project is a validated MVP, but it is still far from the intended
agentic AutoResearch harness.

Missing major capabilities:

- LLM-backed or model-backed `ResearchAgent` that proposes optimization
  directions from objectives, context, metrics, history, and failures
- richer provider-specific LLM clients and prompt templates
- richer `Hypothesis` planning with code/config/prompt mutations beyond the
  current safe search-space mutation protocol
- richer `MemoryManager` retrieval over successful patterns, failure patterns,
  bad cases, domain notes, and semantic similarity beyond the current rule
  based memory index
- full branch lifecycle with trial commits, worktree patch application,
  rollback, remote branch push, and optional PR creation
- stronger `EffectEvaluator` with confidence, regressions, and statistical
  comparison
- `DecisionEngine`: accept, reject, retry, mutate, expand search, or stop
- `RunRegistry`: multi-run comparison, resume, replay, and run lineage
- stronger resume safety checks, such as command fingerprints, environment
  fingerprints, and duplicate memory-write prevention
- real business executors instead of deterministic simulations
- release discipline and richer documentation

## Next Engineering Milestone

Build `v0.3 applied research integration`.

Preferred first implementation:

1. Add a real mutation interface for code/config/prompt changes beyond task
   artifact materialization.
2. Capture optional trial commits per hypothesis.
3. Continue strengthening memory retrieval beyond the current lightweight
   relevance index, especially supporting trials and failure patterns.
4. Add one semi-real executor, such as prompt eval against a real model or a
   business offline-eval command adapter.
5. Expand GitHub CI beyond unit tests when real executors are available.

This should be implemented incrementally, with each step validated locally and
pushed after tests pass.

## Engineering Principles

- Keep the harness generic; avoid baking one business scenario into the core.
- Put scenario-specific behavior behind adapters.
- Preserve traceability for every recommendation.
- Treat failures as first-class learning signals, not just failed runs.
- Prefer a working deterministic loop before adding LLM calls.
- Make artifacts readable and replayable before building UI or dashboards.
- Do not let the project regress into a simple parameter sweep tool.
