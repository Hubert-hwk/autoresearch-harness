# Contributing to autoresearch-harness

Thank you for helping make autonomous experiments more auditable and
reproducible.

## Development setup

```bash
git clone https://github.com/Hubert-hwk/autoresearch-harness.git
cd autoresearch-harness
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests
```

## Contribution expectations

- Preserve the generic `TaskSpec -> Trial -> Result -> Decision` protocol.
- Retain failures, rejected candidates, and negative evidence.
- Add success-path and failure-path tests for behavior changes.
- Document any new trust, execution, or reproducibility boundary.
- Keep runs, datasets, paper PDFs, evidence memory, and `dev-logs/` out of Git.

## Pull requests

Use a focused branch and keep each pull request scoped to one concern. Explain
the motivation, behavioral change, verification performed, and any known
limitations. All CI jobs must pass before merge.

By contributing, you agree that your contribution is licensed under the
Apache License 2.0.
