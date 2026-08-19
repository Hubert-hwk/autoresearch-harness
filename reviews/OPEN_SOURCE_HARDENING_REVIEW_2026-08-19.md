# Open-source hardening review — 2026-08-19

## Objective

Move `autoresearch-harness` from a technically complete research repository
toward a trustworthy, discoverable, and installable open-source AI
infrastructure project without inventing benchmark or release claims.

## Completed in this increment

- Added Apache-2.0 licensing with SPDX package metadata.
- Completed project metadata, URLs, authorship, keywords, classifiers, and the
  `src` package discovery configuration.
- Added contribution, security, citation, and changelog documents.
- Removed the zero-star badge and added the license badge.
- Documented the exact LLM environment variables and current provider boundary.
- Added a capability comparison that distinguishes built-in behavior from
  custom integrations without understating Optuna or MLflow.
- Added a reproducible BPR evidence snapshot with the actual `needs_review`
  decision and limitations instead of presenting an unverified improvement.
- Expanded CI tests to Python 3.10–3.12 and added built-wheel install/CLI smoke
  testing.
- Added 10 GitHub topics and an About description.

## Verification evidence

- Unit tests: 43 passed.
- BPR audit rerun: reproduced candidate delta `+0.031614`, observed noise
  `0.082306`, and decision `needs_review`.
- Isolated wheel build: produced
  `autoresearch_harness-0.3.0.dev0-py3-none-any.whl`.
- Fresh-environment install: installed the wheel and NumPy 2.2.6 successfully;
  `autoresearch --help` and package version import both passed outside the
  repository checkout.
- README and patch whitespace checks: passed.

## Review findings

The package is now buildable and the homepage makes fewer unsupported claims.
The most important remaining credibility gap is not copywriting: it is a
versioned, paired-seed MovieLens benchmark whose verification and replay bundle
can be inspected independently.

## Deferred deliberately

- PyPI installation wording remains absent until a real distribution is
  published.
- No GitHub Release or `v0.3.0` tag exists yet; `0.3.0.dev0` remains accurate.
- The MovieLens Results table remains unpublished until paired verification is
  complete.
- A demo GIF should be recorded from real CLI output after the release-facing
  progress display is finalized.
- A separate 1280×640, sub-1 MB social preview still needs to be created and
  uploaded through repository settings.
- Branch protection should be enabled after the expanded CI job names have run
  once on a pull request.

## Next gate

Run CI on the hardening branch. If it passes, merge the metadata/documentation
increment, then implement the versioned MovieLens verification pack before
creating the `v0.3.0` release and configuring PyPI Trusted Publishing.
