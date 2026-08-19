# MovieLens 100K BPR verification — 2026-08-19

This benchmark is a versioned evidence record for the harness, not a claim of
state-of-the-art recommendation quality. It reports the decision contract,
positive result, negative tradeoffs, and replay outcome together.

## Dataset

- Source: [GroupLens MovieLens 100K](https://files.grouplens.org/datasets/movielens/ml-100k.zip)
- Conversion: retain ratings >= 4 as implicit positive feedback
- Prepared interactions: 55,375
- Users: 942
- Items: 1,447
- Converted CSV SHA-256:
  `180b8db8d6b0d16dd46540919ab29535ada2e5407d082e2038d14b837bda4c49`

The raw and converted datasets are excluded from Git. Run
`python scripts/prepare_movielens_100k.py` to reproduce the input locally.

## Selection and verification protocol

The exploratory search evaluated 12 configurations using seeds `20260612`,
`20260613`, and `20260614`. It selected the candidate parameters in
`examples/recommender_movielens_100k/candidate_params.json`. Verification then
used five different seeds (`20260801`–`20260805`) and alternated baseline-first
and candidate-first execution order.

The baseline and candidate share factors=8, learning_rate=0.05,
regularization=0.001, and one negative sample. The only difference is 3 versus
6 epochs. The predeclared gates were:

- 95% paired bootstrap interval with 5,000 resamples;
- lower interval bound greater than +0.001 NDCG@10;
- candidate guardrail pass rate of 100%;
- complete 5-seed pairs and no execution fingerprint drift.

## Result

| Metric (mean) | Baseline | Candidate | Change |
|---|---:|---:|---:|
| NDCG@10 | 0.033580 | 0.038026 | +0.004446 |
| HitRate@10 | 0.062420 | 0.074098 | +0.011677 |
| Coverage@10 | 0.135867 | 0.088321 | -0.047546 |
| Training time | 3.327 s | 6.533 s | +3.206 s |

- Paired NDCG improvements:
  `[0.011130, 0.003042, 0.004710, -0.000680, 0.004027]`
- 95% bootstrap interval: `[0.0013394, 0.0082284]`
- Promotion decision: `promote`
- Candidate guardrail pass rate: `1.0`
- Verification fingerprint drift: none
- Replay: `matched`, 10 trials, 0 mismatches

The candidate is promoted only under the declared contract. Catalog coverage
fell 34.99%, and training time rose 96.37%. Coverage was observable but not a
gate in this protocol; a follow-up protocol should treat coverage as a paired
non-regression gate if catalog breadth is a product requirement.

## Reproduce

```bash
python scripts/prepare_movielens_100k.py

autoresearch verify-run \
  examples/recommender_movielens_100k/task.json \
  examples/recommender_movielens_100k/baseline_params.json \
  examples/recommender_movielens_100k/candidate_params.json \
  --runs-dir runs/movielens-verification \
  --repo-root .

autoresearch replay \
  runs/movielens-verification/verify_... \
  --runs-dir runs/movielens-replay
```

Machine-readable observations and source evidence hashes are in
[`summary.json`](summary.json). Runtime values are machine-dependent and are
not replay comparison metrics; ranking metrics, coverage, and seed counts are.
