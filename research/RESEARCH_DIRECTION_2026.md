# AutoResearch Harness: 2026 Research Review and Technical Direction

Date: 2026-08-19

## Executive conclusion

The next version should not aim to become an automatic paper-writing system or
add more deterministic demo adapters. It should become an **auditable empirical
software optimization engine**:

> Given a scorable business or engineering task, create isolated code/config/
> prompt candidates, explore them as a lineage-aware search graph, allocate
> compute adaptively, evaluate them with independent and reproducible gates,
> and retain typed evidence that can be verified later.

This direction preserves the repository's original intent while adopting the
strongest recurring result across AIDE, AI Scientist-v2, ERA, AlphaEvolve, GEPA,
Hyperband/BOHB, and the latest verification research. The immediate milestone
should be a real command-backed executor plus patch/worktree mutation and an
experiment graph. Multi-agent role proliferation, paper generation, a vector
database, and UI work should wait.

## Research method

The review used 24 primary papers plus first-party Nature and Google Research
reports. Papers were selected around five questions:

1. What search structure works for long-running automated experimentation?
2. How should executable changes and evaluator feedback be represented?
3. How should limited compute be allocated?
4. What evidence is necessary for reproducibility and trustworthy decisions?
5. What forms of memory actually help rather than contaminate later work?

The local archive and source links are in
[`literature/README.md`](literature/README.md). Claims below summarize the
papers; the proposed architecture is an inference for this repository.

## What the literature says

### 1. Linear optimize-and-retry loops are being replaced by search trees and archives

- AIDE treats ML engineering as tree search in code space, reusing and refining
  promising solutions rather than repeatedly starting over.
- AI Scientist-v2 explicitly replaces its predecessor's linear refinement loop
  with parallel agentic tree search. Each node stores code, plan, runtime,
  metrics, errors, plots, feedback, and status; selected nodes seed later
  experimental stages.
- ERA combines LLM code rewriting with tree search and external research ideas.
  It reports expert-level results across multiple scorable scientific tasks.
- AlphaEvolve and Darwin Godel Machine retain populations/archives so that
  diverse stepping stones survive instead of collapsing immediately to one
  incumbent.

**Project inference:** the current `baseline -> one hypothesis -> one focused
candidate` shape is now the largest architectural limitation. The next core
abstraction should be `ExperimentNode` plus lineage and an archive, not another
hard-coded hypothesis rule.

### 2. Rich execution feedback is more useful than a single scalar reward

- GEPA combines global scores with per-module textual feedback, execution traces,
  reflective mutation, crossover, and Pareto-based candidate retention. It
  reports higher sample efficiency than the compared reinforcement-learning and
  prompt-optimization baselines.
- TextGrad similarly treats natural-language feedback as an optimization signal
  over compound systems.
- The latest long-horizon evaluation finds that final score alone hides whether
  failures came from solution framing, execution, or feedback control.

**Project inference:** executors should return a structured `EvaluationBundle`
containing scalar metrics, guardrail results, failure taxonomy, logs, evaluator
feedback, resource use, and artifact references. The mutation agent should see
this bundle, not only `analysis.json` and aggregated failure counts.

### 3. Budget allocation must be adaptive and multi-fidelity

- Hyperband shows that weak configurations can be stopped early and resources
  progressively concentrated on promising ones.
- BOHB adds model-guided proposal while preserving robust multi-fidelity
  allocation.
- RE-Bench shows a time-horizon effect: the best evaluated agents were much
  stronger than humans at a two-hour budget, while humans scaled better at long
  horizons and overtook agents at larger budgets.

**Project inference:** `max_trials` is insufficient. Tasks need explicit
budgets for wall time, evaluator calls, tokens/cost, seeds, dataset fraction,
epochs, and concurrency. Promotion should happen between fidelity levels.

### 4. Verification, not artifact generation, is the strategic bottleneck

- PaperBench's best tested agent achieved a 21% average replication score on 20
  ICML papers using 8,316 author-developed rubric items.
- ScienceAgentBench reports only 32.4% independent solve rate for the best
  evaluated agent under three attempts.
- MLE-bench reports Kaggle-bronze-level performance on 16.9% of competitions for
  its strongest evaluated setup.
- CORE-Bench's strongest reported baseline reached 21% on its hardest
  computational reproducibility task.
- The August 2026 verification-gap survey reports that code release is common in
  its runnable-system corpus, but only 38% release seeds or execution traces and
  38% report a novelty-verification method. It recommends disclosing human entry
  points, attempts and selection policy, baseline provenance, independent
  review, and preregistered hypotheses.
- AI Scientist-v2 itself cautions that only one of three submissions passed a
  workshop review and that workshop acceptance is not evidence of consistent
  top-tier scientific quality.

**Project inference:** provenance is already a relative strength of this
repository and should become its product identity. A decision must be linked to
an immutable environment, exact mutation, all attempts (not only the winner),
seed set, evaluator version, baseline budget, and selection policy. The model
that proposes a candidate should not be the sole authority accepting it.

### 5. Similarity-based lesson retrieval is not sufficient memory

- MemoryAgentBench separates accurate retrieval, test-time learning,
  long-range understanding, and selective forgetting; current systems do not
  master all four.
- AMA-Bench finds that practical agent memory needs causal and objective
  information that similarity retrieval tends to lose. Its causal-graph and
  tool-assisted AMA-Agent reaches 57.22% average accuracy, 11.16 percentage
  points above the strongest compared memory baseline.
- The latest long-horizon study finds that prior experience can help or mislead,
  and that harness design affects stability.
- The verification-gap survey treats every reused memory as a claim that must
  retain temporal validity and provenance.

**Project inference:** the current keyword-scored `lessons.jsonl` is an
acceptable seed but should not evolve first into a generic vector database.
Memory should be rebuilt from typed experiment evidence: task fingerprint,
  ancestor, mutation, causal rationale, evaluation conditions, outcome,
  uncertainty, validity interval, and supersession links.

### 6. Human control remains useful at high-impact boundaries

- Agent Laboratory reports materially better research quality with human
  feedback at stage boundaries.
- AI co-scientist is designed as a collaborator with generation, reflection,
  ranking, evolution, proximity, and meta-review roles rather than an
  ungoverned autonomous process.
- Self-improving coding-agent work emphasizes sandboxing, observability, and
  oversight as safety mechanisms.

**Project inference:** autonomy should be a policy setting. Expensive runs,
guardrail waivers, external side effects, promotion to a real branch, and final
deployment should support explicit approval gates.

## Gap analysis against the current repository

| Capability | Current implementation | Required next state |
|---|---|---|
| Candidate representation | One narrowed task search space | Immutable code/config/prompt patch node |
| Search topology | Baseline plus one candidate per round | DAG/tree with lineage, archive, branching and pruning |
| Search policy | Grid enumeration and rule-based narrowing | Pluggable random, successive-halving, UCB/tree and Pareto policies |
| Execution | Three simulations and one BPR adapter | Generic command executor in an isolated workspace |
| Isolation | Optional switch of the active Git branch | Disposable Git worktree or sandbox per candidate |
| Feedback | Metrics and aggregate failure reasons | Structured metrics, textual diagnostics, logs and resource usage |
| Budget | Trial count | Wall time, cost, tokens, fidelity, seeds and concurrency |
| Reproducibility | Task/diff/artifact provenance | Environment, command, dependency, dataset and evaluator fingerprints |
| Statistics | Metric delta and combined standard deviation | Replication policy, confidence intervals and paired comparisons |
| Memory | Keyword-ranked lesson JSONL | Typed evidence graph with causality, validity and supersession |
| Governance | Decision labels and branch disposition | Approval gates, independent evaluator and policy audit trail |

## Recommended v0.3 milestone

Name: **Applied Research Execution Core**

The milestone is complete when the harness can optimize a small real repository
task by editing code or configuration in isolated worktrees, executing a declared
evaluation command, exploring multiple related candidates under a fixed budget,
and reproducing the winning decision from stored artifacts.

### Phase 1: Real task and evaluator contract

Add a versioned task schema with:

- editable paths and allowed mutation types;
- setup, train/evaluate, and validation commands;
- primary, guardrail, and diagnostic metrics;
- dataset split/fingerprint requirements;
- wall-time, cost, seed, and concurrency budgets;
- fidelity dimensions such as epochs, data fraction, or test subset;
- approval policy and side-effect declaration.

Implement an `ExternalCommandExecutor` that runs commands with timeouts, captures
stdout/stderr and exit status, parses a machine-readable metrics file, records
resource usage, and rejects undeclared output paths.

### Phase 2: Patch mutation and workspace isolation

Generalize `mutation.v1` into typed operations:

- `task_search_space_replace` for compatibility;
- `text_patch` for prompts/configuration;
- `git_patch` for code;
- optional `generated_file` under an allowlist.

Every candidate should execute in a disposable Git worktree or equivalent
sandbox rooted at the recorded base commit. Store the patch, parent node,
content hashes, command/environment fingerprint, and complete artifact manifest.
Do not use `git switch` on the user's active worktree for experiment isolation.

### Phase 3: Experiment graph and adaptive scheduler

Introduce:

```text
ExperimentNode
  id, parent_ids, hypothesis, mutation, workspace
  fidelity, budget_spent, status
  evaluation_bundle, decision, artifact_refs
```

Start with three deterministic policies:

1. `random` as a baseline;
2. `successive_halving` for early stopping and promotion;
3. `pareto_archive` for quality, guardrails, cost, and diversity.

Then add an LLM mutation proposer that receives parent trajectories and
structured evaluator feedback. Tree/UCB selection can follow once deterministic
policies and replay tests are stable.

### Phase 4: Verification-grade decisions

- Pre-register each hypothesis and evaluator before execution.
- Separate proposer and acceptance evaluator identities.
- Preserve failed, timed-out, and dominated attempts.
- Require repeated seeds for stochastic tasks and record the promotion rule.
- Add paired comparisons or bootstrap confidence intervals where applicable.
- Store environment, dependency, dataset, code, command, and evaluator hashes.
- Add a `replay --node <id>` command that reconstructs and checks a candidate.

### Phase 5: Evidence-based memory

Derive memory from experiment nodes rather than free-form summaries. Retrieval
should first filter by task/environment/evaluator compatibility, then rank by
causal relevance. Contradictory evidence should create supersession edges rather
than silently coexist as equally valid lessons.

## First vertical validation task

Use one small, cheap, real code optimization task before integrating an online
model API. A suitable fixture would be:

- a committed Python ranking/recommendation implementation;
- editable model or feature code, not only JSON parameters;
- a fixed train/validation/test split;
- a fast evaluation command producing `metrics.json`;
- at least two fidelity levels and three seeds;
- a latency or memory guardrail;
- a hidden test split used only by the final evaluator.

This fixture exercises patching, isolation, execution, adaptive scheduling,
statistics, and replay without introducing provider nondeterminism or API cost.
After that works, add a real prompt-evaluation adapter with recorded model,
sampling parameters, token cost, request/response hashes, and a held-out set.

## Acceptance criteria

The v0.3 milestone should satisfy all of the following:

1. No experiment changes the user's active worktree.
2. Every node can be reconstructed from base commit plus stored mutation.
3. A killed run resumes without duplicating completed evaluations or memory.
4. The scheduler never exceeds declared wall-time, cost, seed, or trial budgets.
5. Promotion decisions include uncertainty and all guardrail evidence.
6. Failed and rejected attempts remain queryable and linked in provenance.
7. Replaying a deterministic node reproduces its metrics within a declared
   tolerance.
8. The final report discloses attempts, selection policy, baseline provenance,
   seeds, evaluator identity, and any human intervention.

## What not to prioritize yet

- Automatic manuscript generation: outside the project's business/engineering
  optimization goal and does not address the verification bottleneck.
- More hard-coded simulated adapters: they add breadth without testing the core
  missing capability.
- A large multi-agent organization: search structure and evaluator quality have
  stronger evidence than role count.
- A vector database for memory: causality, validity, and provenance are the
  missing semantics, not storage scale.
- GitHub PR automation or a dashboard: useful after isolated execution and
  replay are trustworthy.
- Training or self-modifying the research agent itself: premature until the
  harness can independently evaluate and safely contain mutations.

## Final direction

The repository should position itself between classic AutoML and autonomous
coding agents:

```text
AutoML search discipline
  + LLM-generated code/config/prompt mutations
  + evaluator-driven tree/archive search
  + multi-fidelity resource allocation
  + verification-grade provenance and replay
  + human-governed promotion
```

That is narrower than a general AI Scientist, but more useful and defensible for
the repository's stated business and engineering optimization mission. It also
builds on what the project already does well—bounded execution, guardrails,
artifacts, resume, and provenance—instead of discarding those strengths to copy
paper-generation systems.
