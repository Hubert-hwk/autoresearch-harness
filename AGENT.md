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
```

Implemented modules:

- `hypothesis.py`: first-class `Hypothesis` and `TrialPlan`
- `agent.py`: deterministic rule-based research planner
- `branching.py`: branch metadata recording and optional branch creation
- `effect.py`: baseline-vs-candidate comparison
- `memory.py`: JSONL-backed memory streams
- `agentic.py`: orchestration for the agentic research loop
- `llm.py`: provider-agnostic LLM client interface placeholder

Supported deterministic validation scenarios:

- search/ranking parameter tuning
- prompt tuning
- model serving parameter tuning

Validation command:

```powershell
python -m autoresearch_harness research examples\prompt_tuning\task.json --branch-mode record
```

The loop currently uses `record` branch mode in validation, so it records the
experiment branch identity without switching the active worktree branch.

Git state at the time these notes were added:

- local git repository exists
- initial commit exists: `9afc4e6 Initial autoresearch harness MVP`
- GitHub remote has not been configured or pushed yet

## Gap To Desired System

The current project is a validated MVP, but it is still far from the intended
agentic AutoResearch harness.

Missing major capabilities:

- LLM-backed or model-backed `ResearchAgent` that proposes optimization
  directions from objectives, context, metrics, history, and failures
- provider-specific LLM clients, such as OpenAI-compatible API adapters
- richer `Hypothesis` planning with code/config/prompt mutations
- richer `MemoryManager` retrieval over lessons, successful patterns, failure
  patterns, bad cases, and domain notes
- full `BranchManager` lifecycle with trial commits, diff capture, rollback,
  and optional PR creation
- stronger `EffectEvaluator` with confidence, regressions, and statistical
  comparison
- `DecisionEngine`: accept, reject, retry, mutate, expand search, or stop
- `RunRegistry`: multi-run comparison, resume, replay, and run lineage
- real business executors instead of deterministic simulations
- GitHub remote, CI, release discipline, and richer documentation

## Next Engineering Milestone

Build `v0.3 applied research integration`.

Preferred first implementation:

1. Add a real mutation interface for code/config/prompt changes.
2. Capture diffs and optional trial commits per hypothesis.
3. Add stronger memory retrieval that ranks relevant lessons and supporting
   trials, not just recent JSONL records.
4. Add one semi-real executor, such as prompt eval against a real model or a
   business offline-eval command adapter.
5. Add GitHub CI and push the repository to a remote baseline.

This should be implemented locally first. After the v0.2 loop is demonstrable,
push the repository to GitHub as the first meaningful public or private remote
baseline.

## Engineering Principles

- Keep the harness generic; avoid baking one business scenario into the core.
- Put scenario-specific behavior behind adapters.
- Preserve traceability for every recommendation.
- Treat failures as first-class learning signals, not just failed runs.
- Prefer a working deterministic loop before adding LLM calls.
- Make artifacts readable and replayable before building UI or dashboards.
- Do not let the project regress into a simple parameter sweep tool.
