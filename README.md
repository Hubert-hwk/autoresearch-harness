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

If the package is installed in your project virtual environment, the same demo
can also be launched with:

```powershell
python -m autoresearch_harness run examples\ranking_param_tuning\task.json
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
- `hypothesis.json`: agent-proposed optimization direction
- `branch.json`: experiment branch metadata
- `effect.json`: baseline-vs-candidate comparison
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
`src/autoresearch_harness/llm.py`. No real model API is wired by default yet;
the project intentionally keeps the harness stable with a deterministic agent
before adding provider-specific LLM clients.

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
