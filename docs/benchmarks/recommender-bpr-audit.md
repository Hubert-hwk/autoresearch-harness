# Recommender BPR development audit

This page records a real development audit used in the README evidence
snapshot. It is a smoke-scale validation of the workflow, not a benchmark
against another recommender system and not a production performance claim.

## Scope

- Date: 2026-08-19
- Source revision: `8cee40c8b61491bcba9d295ddc8648fc7a4614db`
- Task: `examples/recommender_bpr/task.json`
- Dataset: the versioned toy interaction data in
  `examples/recommender_bpr/interactions.csv`
- Agent: deterministic rule agent
- Primary metric: NDCG@10
- Guardrails: hit rate at 10 and training time

## Reproduction

From an editable installation of the repository:

```bash
autoresearch research \
  examples/recommender_bpr/task.json \
  --agent rule \
  --runs-dir runs/readme-bpr-audit
```

The command records the resolved task, baseline and candidate trials, mutation
plan, effect, decision, event stream, provenance, and Markdown report under the
selected runs directory.

## Observed result

| Field | Value |
|---|---:|
| Baseline best NDCG@10 | 0.187161 |
| Focused candidate best NDCG@10 | 0.218775 |
| Point delta | +0.031614 |
| Observed metric noise | 0.082306 |
| Baseline trial budget | 8 |
| Candidate trial budget | 4 |
| Decision | `needs_review` |
| Next action | `run_more_seeds_or_expand_validation` |

Both searches satisfied the configured guardrails. The point improvement was
smaller than the observed noise estimate, so the candidate was not promoted.

## Limitations

- The dataset is intentionally tiny and exists to exercise real NumPy model
  training in tests and examples.
- Baseline and candidate values are best-of-search point estimates, not a
  paired repeated-seed confidence interval.
- Runtime varies by machine and is not reported as a cross-system benchmark.
- A publishable recommendation result requires a versioned real dataset,
  paired seeds, replay verification, and a retained evidence bundle.

The next benchmark milestone is to complete that protocol on MovieLens 100K
and publish the result whether it promotes, rejects, or remains inconclusive.
