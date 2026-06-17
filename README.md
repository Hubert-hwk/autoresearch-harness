# autoresearch-harness

AutoResearch harness MVP for business optimization loops.

See [AGENT.md](AGENT.md) for the project intent, current state, and the
agentic AutoResearch harness roadmap.

This project treats autoresearch as an engineering harness, not as an
automatic paper writer. The first MVP focuses on bounded trial loops:

1. Load a business optimization task.
2. Generate candidate trials from a search space.
3. Execute each trial through a scenario adapter.
4. Evaluate primary and guardrail metrics.
5. Persist traceable run artifacts.
6. Report the best candidate and useful negative results.

## Quick Start

```powershell
.\scripts\run-demo.ps1
```

Run the broader MVP validation suite with:

```powershell
.\scripts\run-validation.ps1
```

Run the first agentic research loop with:

```powershell
python -m autoresearch_harness research examples\prompt_tuning\task.json --branch-mode record
```

Run the model-parameter tuning example with:

```powershell
python -m autoresearch_harness research examples\model_param_tuning\task.json --branch-mode record
```

Run the NumPy BPR recommender example with:

```powershell
python -m autoresearch_harness research examples\recommender_bpr\task.json --branch-mode record
```

Prepare and run the larger MovieLens 100K BPR validation pack with:

```powershell
python scripts\prepare_movielens_100k.py
python -m autoresearch_harness research examples\recommender_movielens_100k\task.json --branch-mode record
```

The MovieLens raw data and converted interactions are written under
`data/external/ml-100k/`, which is intentionally ignored by git. The committed
task file and preparation script make the validation reproducible without
checking benchmark data or generated model artifacts into the repository.

Run a bounded multi-round optimization loop with:

```powershell
.\scripts\autoresearch.ps1 multi-round examples\recommender_bpr\task.json --max-rounds 2 --review-seed-count 5 --branch-mode record
```

The multi-round runner creates `runs/multi_round_<timestamp>/` with per-round
input task snapshots, nested agentic runs, `optimization_trace.jsonl`,
`round_summary.json`, and `report.md`. Accepted candidates are promoted as the
next round's task. `needs_review` recommender rounds keep the same task contract
but expand `metadata.seeds` for stronger validation before promotion.

Inspect the latest agentic run, or a specific run, with:

```powershell
.\scripts\autoresearch.ps1 status
.\scripts\autoresearch.ps1 status --research-id agentic_...
.\scripts\autoresearch.ps1 status --research-id agentic_... --json
```

Resume an interrupted agentic run with:

```powershell
.\scripts\autoresearch.ps1 resume --research-id agentic_...
```

Use a model-backed research planner with an OpenAI-compatible API:

```powershell
$env:AUTORESEARCH_LLM_API_KEY="..."
$env:AUTORESEARCH_LLM_MODEL="gpt-4.1-mini"
python -m autoresearch_harness research examples\model_param_tuning\task.json --agent llm --branch-mode record
```

If the package is installed in your project virtual environment, the same demo
can also be launched with:

```powershell
python -m autoresearch_harness run examples\ranking_param_tuning\task.json
```

For local development without installing the package, prefer the wrapper:

```powershell
.\scripts\autoresearch.ps1 run examples\ranking_param_tuning\task.json
.\scripts\autoresearch.ps1 research examples\model_param_tuning\task.json --branch-mode record
```

The command writes artifacts under `runs/<run_id>/`:

- `task.json`: the resolved task spec
- `trials.jsonl`: every candidate and its result
- `analysis.json`: pass rate, failure reasons, and top trials
- `decisions.jsonl`: harness decisions and stop reason
- `report.md`: compact human-readable summary

The `research` command creates a higher-level `runs/agentic_<timestamp>/`
directory containing:

- baseline and candidate run artifacts
- `state.json`: resumable status, phase, run ids, and final decision
- `events.jsonl`: ordered lifecycle events
- `artifacts.jsonl`: artifact index for reports, metrics, decisions, and inputs
- `provenance.jsonl`: evidence graph linking decisions to supporting artifacts
- `memory_context.json`: ranked prior lessons used by the agent planner
- `hypothesis.json`: agent-proposed optimization direction
- `branch_lifecycle.json`: experiment branch phase and disposition record
- `mutation_plan.json`: validated mutation protocol manifest derived from the
  hypothesis
- `mutation_artifact/candidate_task.json`: materialized candidate task used by
  the candidate run
- `mutation_artifact/mutation.diff`: git no-index diff between the baseline
  task and materialized candidate task
- `branch.json`: experiment branch metadata
- `effect.json`: baseline-vs-candidate comparison
- `decision.json`: accept/reject/retry/needs_review decision and next action
- `agentic_result.json`: complete loop summary
- `report.md`: human-readable agentic run report

## MVP Scope

The included adapters are:

- `ranking_param_tuning`: a local deterministic search/ranking simulation
- `prompt_tuning`: a deterministic prompt optimization simulation
- `model_param_tuning`: a deterministic model serving parameter simulation
- `recommender_bpr`: a small real NumPy BPR recommender training and evaluation
  loop
  with three-seed aggregate metrics, model artifacts, training logs, and dataset
  fingerprints. Runtime metrics separate per-seed mean/std from total trial
  time through `train_time_sec_mean`, `train_time_sec_std`, and
  `train_time_sec_total`.
- `examples/recommender_movielens_100k`: a larger standard benchmark validation
  pack using the same BPR adapter on MovieLens 100K prepared outside the repo

Together they demonstrate that the harness protocol is not tied to one
business scenario.

The first agentic loop is deterministic: a rule-based research agent reads
baseline failure reasons, proposes a focused hypothesis, validates it, compares
effects, and writes memory records under `memory/`.

There is also a provider-agnostic LLM interface in
`src/autoresearch_harness/llm.py`. The default research agent is deterministic;
`--agent llm` uses an OpenAI-compatible chat-completions client configured by
environment variables. The LLM only proposes a bounded hypothesis and candidate
search space; execution, metrics, guardrails, memory, and branch metadata remain
controlled by the harness.

The registry files make a research task inspectable after interruption: the
system can recover which phase completed, which run ids were produced, and
which artifacts contain the evidence trail.
The `resume` command can continue from completed baseline, hypothesis, branch,
or candidate phases without rerunning earlier completed phases.

Before proposing a hypothesis, the agentic loop now builds a lightweight memory
index from `memory/lessons.jsonl`. It ranks prior lessons by executor, failed
guardrails, primary metric, and search-space parameter overlap, writes the
selected context to `memory_context.json`, and links it into provenance as
evidence for the hypothesis.

After branch metadata is prepared, the harness converts the hypothesis into a
`mutation_plan.json` manifest. In the current version, the protocol supports
safe search-space mutations only: the candidate task may narrow parameter
values within the original task bounds, but it cannot introduce unknown
parameters or out-of-contract values. The candidate run is derived from this
manifest rather than directly from free-form agent output.
The mutation plan is then materialized into a candidate task artifact and a
standard git diff. The candidate run reloads that materialized task, so the
actual run input is inspectable and reproducible.

Branch lifecycle is tracked separately from branch metadata. `branch.json`
records the base and experiment branch identity; `branch_lifecycle.json`
records the phases the experiment branch has passed through, including mutation
attachment, candidate execution, final decision, and branch disposition. In
`record` mode the disposition is `record_only`; in real branch mode, accepted
experiments are retained for promotion while rejected or retry-worthy branches
remain available for audit or follow-up.

Agentic runs separate metric comparison from governance decisions:

- `effect.json` records metric deltas and pass-rate deltas
- `decision.json` records the harness decision, confidence, reasons,
  blocking guardrails, and next action
- `provenance.jsonl` records dependencies such as
  `decision -> effect -> candidate analysis -> mutation artifact -> mutation diff`

If a top trial exposes `<primary_metric>_std`, the decision engine treats
primary-metric improvements smaller than the combined baseline/candidate
standard deviation as `needs_review` rather than `accept`. This keeps
multi-seed recommender experiments from promoting changes whose observed gain
is within measurement noise.

The `multi-round` command is the first continuation layer on top of single
agentic runs. It records each round as an auditable child run and only promotes
candidate task artifacts after an `accept` decision. Review-worthy recommender
changes are revalidated with more seeds instead of being silently accepted.

The intended extension points are:

- add real executors under `src/autoresearch_harness/adapters/`
- add richer policies under `src/autoresearch_harness/policy.py`
- add stronger validation gates under `src/autoresearch_harness/evaluation.py`
- plug in prompt/model/search/ad strategy experiments through the same
  `TaskSpec -> Trial -> Result -> Decision` protocol

## Task Contract

The MVP task contract is JSON to keep the first version dependency-free. A task
declares the executor, dataset, budget, search space, primary metric, guardrails,
and optional `metadata`. Scenario-specific execution logic lives in adapters,
while the run loop and artifact protocol stay shared. The BPR recommender
adapter uses `metadata.seeds` when present; otherwise it falls back to the
default three-seed validation set.
