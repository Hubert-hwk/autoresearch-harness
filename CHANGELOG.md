# Changelog

All notable changes to this project will be documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Apache-2.0 licensing and complete Python package metadata.
- Contributor, security, and citation guidance.
- Multi-version test coverage and built-wheel installation smoke testing.
- Accurate README guidance for LLM configuration and benchmark evidence.
- A versioned MovieLens 100K paired-seed verification protocol and transparent
  Results table, including coverage and runtime regressions.

### Fixed

- The BPR executor now honors the seed injected by `verify-run` instead of
  reusing its default multi-seed aggregate for every declared pair.

## [0.3.0-dev] - 2026-08-19

### Added

- Real external-command evaluator and bounded task contract.
- Typed patch mutation in detached Git worktrees.
- Append-only, hash-chained experiment graph.
- Adaptive multi-fidelity scheduling and Pareto archive.
- Paired-seed verification, execution fingerprints, and replay.
- Validity-aware durable evidence memory.

[Unreleased]: https://github.com/Hubert-hwk/autoresearch-harness/compare/v0.3.0...HEAD
