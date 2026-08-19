# MovieLens benchmark stage review — 2026-08-19

## Outcome

The repository now has a runnable MovieLens 100K paired-seed verification
protocol and a replay-matched result. During implementation, a seed-injection
defect in the BPR adapter was found and fixed before any verification claim was
published.

## Evidence

- Dataset: 55,375 implicit interactions, 942 users, 1,447 items.
- Exploration: 12 configurations on three selection seeds.
- Verification: five separate held-out seeds, 10 alternating-order trials.
- Mean NDCG@10: 0.033580 -> 0.038026.
- Paired improvement: +0.0044458; 95% CI [0.0013394, 0.0082284].
- Decision: `promote` under the predeclared +0.001 and guardrail gates.
- Replay: matched, no drift, no mismatches.
- Regression disclosed: coverage -34.99%; mean training time +98.66% on the
  clean-commit evidence run.
- Evidence anchor: clean commit `dfdf496d988467375982dcdc90d444948f424252`.

## Defect review

Before the fix, `verify-run` injected a seed parameter but the BPR executor
ignored it and used its default task-level seed list. That would have made each
declared pair a repeated aggregate rather than an independent seed. The
executor now uses exactly the injected verification seed for that trial, writes
the actual seed into artifacts, and reports `seed_count=1`. A regression test
covers the behavior.

## Stage decision

The result is suitable for a transparent README Results section because the
protocol is versioned and replayed. It is not suitable as a blanket claim that
the candidate is superior: compute cost doubled and catalog coverage fell.

## Next work

Add a paired non-regression gate for observable metrics such as coverage,
retain a portable full evidence bundle as a GitHub Release asset, then record a
real CLI demo from the release candidate.
