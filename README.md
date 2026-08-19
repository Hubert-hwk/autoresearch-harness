<div align="center">
  <h1>autoresearch-harness</h1>

  <p><strong>Turn an optimization idea into bounded experiments, replayable evidence, and a promotion decision.</strong></p>

  <p>
    <a href="https://github.com/Hubert-hwk/autoresearch-harness/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Hubert-hwk/autoresearch-harness/ci.yml?branch=main&style=flat-square&label=CI" alt="CI" /></a>
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
    <img src="https://img.shields.io/badge/roadmap-7%2F7%20phases-22c55e?style=flat-square" alt="7 of 7 phases complete" />
    <img src="https://img.shields.io/badge/tests-43%20passing-0ea5e9?style=flat-square" alt="43 tests passing" />
    <a href="https://github.com/Hubert-hwk/autoresearch-harness/stargazers"><img src="https://img.shields.io/github/stars/Hubert-hwk/autoresearch-harness?style=flat-square" alt="GitHub stars" /></a>
  </p>

  <img src="assets/autoresearch-method-overview.png" width="960" alt="Six-step autoresearch workflow from a versioned task through bounded search, isolated execution, experiment lineage, verification and replay, to validity-aware evidence memory; failures and drift remain retained evidence." />

  <p>
    <a href="#quick-start">Quick Start</a> ·
    <a href="#how-it-works">Architecture</a> ·
    <a href="ROADMAP_V03.md">Roadmap</a> ·
    <a href="research/RESEARCH_DIRECTION_2026.md">Research</a> ·
    <a href="AGENT.md">Project Notes</a>
  </p>
</div>

---

`autoresearch-harness` is an empirical optimization engine for agent-driven
business and engineering research. It runs declared evaluators under explicit
budgets, isolates code changes, preserves the full experiment lineage, verifies
promising candidates across repeated seeds, replays the evidence, and only then
allows a result to become durable memory.

It is built for a different question than “can an agent generate an answer?”:
**can we inspect, reproduce, and trust the evidence behind a change?**

## Why this project

- **Execute real evaluators** — run trusted local commands without shell
  interpolation and retain metrics, logs, artifacts, timing, and hashes.
- **Keep experiments isolated** — apply typed patches inside detached Git
  worktrees without switching or rewriting the active checkout.
- **Preserve every decision** — model experiments as append-only,
  hash-chained nodes with lineage, budget, evaluation, and disposition.
- **Search within hard budgets** — use deterministic random sampling,
  Successive Halving, multi-fidelity promotion, and a Pareto archive.
- **Verify before promotion** — compare baseline and candidate over paired
  seeds with deterministic bootstrap intervals and independent guardrail gates.
- **Remember only replayed evidence** — admit durable claims only after a
  complete, drift-free verification and matched replay.

## Quick Start

The deterministic command-backed example needs no API key:

```bash
git clone https://github.com/Hubert-hwk/autoresearch-harness.git
cd autoresearch-harness
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
autoresearch run examples/external_command/task.json
```

Run the complete test suite:

```bash
python -m unittest discover -s tests
```

<details>
<summary><strong>Windows PowerShell</strong></summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
.\scripts\autoresearch.ps1 run examples\external_command\task.json
.\scripts\run-validation.ps1
```

</details>

## What you can run

| Capability | Command | Evidence produced |
|---|---|---|
| Bounded task evaluation | `autoresearch run TASK` | trials, analysis, decisions, report |
| Agentic research loop | `autoresearch research TASK` | hypothesis, mutation, effects, provenance |
| Isolated source patch | `autoresearch patch-run TASK PATCH` | worktree, diff, audits, hashes |
| Experiment graph audit | `autoresearch graph-status GRAPH_DIR` | validated graph snapshot |
| Multi-fidelity search | `autoresearch adaptive-run TASK` | promotions, budgets, Pareto archive |
| Independent verification | `autoresearch verify-run TASK BASELINE CANDIDATE` | paired interval, fingerprints, manifest |
| Scientific replay | `autoresearch replay VERIFICATION_DIR` | drift and metric-match report |
| Durable evidence memory | `autoresearch memory-ingest VERIFY_DIR REPLAY_RESULT` | typed claim and archived evidence bundle |

### Verify, replay, remember

```bash
autoresearch verify-run \
  examples/external_command/task.json \
  examples/external_command/baseline_params.json \
  examples/external_command/candidate_params.json \
  --repo-root .

autoresearch replay runs/verify_...

autoresearch memory-ingest \
  runs/verify_... \
  runs/replay_.../replay_result.json \
  --memory-dir memory

autoresearch memory-query \
  examples/external_command/task.json \
  --memory-dir memory \
  --repo-root .
```

## How it works

```mermaid
flowchart LR
    T["Versioned TaskSpec"] --> S["Bounded Search"]
    S --> E["Trusted Evaluator"]
    E --> G["Experiment Graph"]
    G --> V["Paired Verification"]
    V --> R["Fingerprint-Gated Replay"]
    R -->|"matched"| M["Evidence Memory"]
    R -->|"drift or mismatch"| X["Retained Negative Evidence"]
    M --> P["Next Research Plan"]
    P --> S
```

The durable path is intentionally narrower than the exploratory path:

```text
hypothesis → candidate → evaluation → verification → replay → evidence memory
                                      any failure ────────→ retained evidence
```

### Evidence contracts

| Contract | Purpose | Integrity boundary |
|---|---|---|
| `task.v2` | task, metrics, budgets, execution and mutation policy | strict schema validation |
| `patch.v1` | bounded UTF-8 source changes | allowlisted paths + pre/post audit |
| experiment events | immutable research lineage | sequence + SHA-256 hash chain |
| `scheduling.v1` | deterministic multi-fidelity allocation | global trial/time/fidelity budgets |
| `verification.v1` | repeated-seed promotion gate | paired interval + guardrail gates |
| `fingerprint.v1` | execution identity | task/data/code/runtime components |
| `replay.v1` | exact scientific reproduction | manifest hash + metric tolerance |
| `evidence-memory.v1` | reusable verified knowledge | replay admission + validity + supersession |

## Artifacts, not hidden state

Every run writes inspectable JSON, JSONL, Markdown, logs, and hashes under its
run directory. Depending on the command, this includes:

- resolved task and parameter snapshots;
- every successful, failed, timed-out, dominated, or rejected trial;
- stdout, stderr, metrics, declared artifacts, and SHA-256 digests;
- patch diffs, worktree identity, and filesystem audits;
- append-only experiment and memory event streams;
- paired statistics, execution fingerprints, and replay manifests;
- human-readable reports and machine-readable decisions.

Generated runs, datasets, memory, and local development logs are Git-ignored.

## Included evaluators

| Adapter | What it demonstrates | External dependency |
|---|---|---|
| `external_command` | real command execution and artifact capture | trusted local command |
| `recommender_bpr` | real multi-seed NumPy model training | NumPy |
| `ranking_param_tuning` | deterministic ranking optimization | none |
| `prompt_tuning` | bounded prompt-policy simulation | none |
| `model_param_tuning` | serving-parameter simulation | none |

The repository also includes a MovieLens 100K preparation and validation pack.
Raw benchmark data is downloaded outside version control.

## Safety model

The harness treats task files and evaluators as **trusted executable input**.
It prevents shell interpolation, constrains declared patches, preserves the
active worktree, checks evaluator side effects, enforces budgets, and detects
evidence drift. A detached Git worktree is source isolation—not an OS or
container security sandbox.

Do not run untrusted task definitions or evaluators without an external sandbox.

## Roadmap

The seven-phase v0.3 execution-core plan is complete:

- [x] Phase 0 — research baseline and architecture decision
- [x] Phase 1 — real command execution contract
- [x] Phase 2 — typed patch mutation and worktree isolation
- [x] Phase 3 — immutable experiment graph
- [x] Phase 4 — adaptive multi-fidelity scheduling
- [x] Phase 5 — verification, fingerprints, and replay
- [x] Phase 6 — validity-aware evidence memory

Next work is stabilization: multi-writer coordination, stronger sequential
statistics, signed provenance, OS-level isolation, and release discipline. See
[ROADMAP_V03.md](ROADMAP_V03.md) and the phase reviews under [reviews/](reviews/).

## Research basis

The architecture follows a primary-source review of automated empirical
research, software engineering agents, search and resource allocation,
verification benchmarks, and long-term agent memory. The synthesized direction
and paper index are available in:

- [Research direction](research/RESEARCH_DIRECTION_2026.md)
- [Literature index](research/literature/README.md)

Third-party paper PDFs are intentionally excluded from Git; the index links to
their original sources.

## Contributing

Issues and focused pull requests are welcome. A useful contribution should:

1. preserve the generic `TaskSpec → Trial → Result → Decision` protocol;
2. retain negative and failed evidence rather than silently dropping it;
3. add tests for new success and failure paths;
4. document the trust and reproducibility boundary it introduces.

For architecture context, start with [AGENT.md](AGENT.md). For implementation
sequencing, see [ROADMAP_V03.md](ROADMAP_V03.md).

---

<div align="center">
  <strong>Auditable experiments over unverifiable automation.</strong><br />
  <sub>If this direction is useful, consider starring the repository or opening a focused issue.</sub>
</div>
