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
- `hypothesis.json`: agent-proposed optimization direction
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

Agentic runs separate metric comparison from governance decisions:

- `effect.json` records metric deltas and pass-rate deltas
- `decision.json` records the harness decision, confidence, reasons,
  blocking guardrails, and next action

The intended extension points are:

- add real executors under `src/autoresearch_harness/adapters/`
- add richer policies under `src/autoresearch_harness/policy.py`
- add stronger validation gates under `src/autoresearch_harness/evaluation.py`
- plug in prompt/model/search/ad strategy experiments through the same
  `TaskSpec -> Trial -> Result -> Decision` protocol

## Task Contract

The MVP task contract is JSON to keep the first version dependency-free. A task
declares the executor, dataset, budget, search space, primary metric, and
guardrails. Scenario-specific execution logic lives in adapters, while the run
loop and artifact protocol stay shared.
