# AutoResearch Literature Index

This index records the primary papers used for the August 2026 technical
direction review of `autoresearch-harness`. The selection focuses on autonomous
research agents, empirical code optimization, evaluation, reproducibility,
long-horizon memory, and budget-aware search.

Paper links point to their public arXiv records and PDFs. The local research
workspace used a dated PDF snapshot, but third-party PDFs are intentionally not
distributed with this repository. Inclusion is not a claim that every preprint
has passed peer review; the arXiv identifier remains the stable reference when
a later version exists.

## Core systems and search methods

| Year | Work | Why it matters here | Source |
|---|---|---|---|
| 2026 | [An AI system to help scientists write expert-level empirical software](https://arxiv.org/abs/2509.06503) | Defines scorable empirical software and combines LLM code mutation with tree search and external research ideas. | [arXiv PDF](https://arxiv.org/pdf/2509.06503) |
| 2026 | [Towards End-to-End Automation of AI Research](https://arxiv.org/abs/2606.15497) | Latest end-to-end AI Scientist report and Nature-version evidence. | [arXiv PDF](https://arxiv.org/pdf/2606.15497) |
| 2025 | [The AI Scientist-v2](https://arxiv.org/abs/2504.08066) | Replaces a linear loop with staged, parallel agentic tree search and replicated experiments. | [arXiv PDF](https://arxiv.org/pdf/2504.08066) |
| 2025 | [AIDE](https://arxiv.org/abs/2502.13138) | Frames ML engineering as tree search over executable code solutions. | [arXiv PDF](https://arxiv.org/pdf/2502.13138) |
| 2025 | [AlphaEvolve](https://arxiv.org/abs/2506.13131) | Demonstrates evaluator-driven evolutionary code search on scientific and production problems. | [arXiv PDF](https://arxiv.org/pdf/2506.13131) |
| 2025 | [Darwin Godel Machine](https://arxiv.org/abs/2505.22954) | Maintains a diverse archive and empirically validates self-modifying coding agents. | [arXiv PDF](https://arxiv.org/pdf/2505.22954) |
| 2025 | [A Self-Improving Coding Agent](https://arxiv.org/abs/2504.15228) | Shows scaffold self-modification and emphasizes observability and sandboxing. | [arXiv PDF](https://arxiv.org/pdf/2504.15228) |
| 2025 | [GEPA](https://arxiv.org/abs/2507.19457) | Uses execution traces, textual feedback, reflection, and Pareto selection rather than scalar reward alone. | [arXiv PDF](https://arxiv.org/pdf/2507.19457) |
| 2024 | [TextGrad](https://arxiv.org/abs/2406.07496) | Treats natural-language feedback as an optimization signal for compound AI systems. | [arXiv PDF](https://arxiv.org/pdf/2406.07496) |
| 2024 | [The AI Scientist](https://arxiv.org/abs/2408.06292) | Early complete idea-to-experiment-to-paper research loop and an important baseline. | [arXiv PDF](https://arxiv.org/pdf/2408.06292) |
| 2025 | [Agent Laboratory](https://arxiv.org/abs/2501.04227) | Provides evidence for staged research roles and the value of human feedback gates. | [arXiv PDF](https://arxiv.org/pdf/2501.04227) |
| 2025 | [Towards an AI Co-Scientist](https://arxiv.org/abs/2502.18864) | Uses generation, reflection, ranking, evolution, and meta-review agents for hypothesis search. | [arXiv PDF](https://arxiv.org/pdf/2502.18864) |

## Evaluation, verification, and reproducibility

| Year | Work | Why it matters here | Source |
|---|---|---|---|
| 2026 | [Autonomous Research Agents: A Survey of AI Scientists and the Verification Gap](https://arxiv.org/abs/2608.05179) | Latest survey used here; separates artifact production from independently verified claims. | [arXiv PDF](https://arxiv.org/pdf/2608.05179) |
| 2026 | [Beyond Final Scores](https://arxiv.org/abs/2608.13417) | Evaluates solution framing, execution, feedback control, and experience reuse instead of only final scores. | [arXiv PDF](https://arxiv.org/pdf/2608.13417) |
| 2025 | [PaperBench](https://arxiv.org/abs/2504.01848) | Uses author-developed hierarchical rubrics to evaluate full research replication. | [arXiv PDF](https://arxiv.org/pdf/2504.01848) |
| 2024 | [RE-Bench](https://arxiv.org/abs/2411.15114) | Compares agents and human experts at multiple time budgets on open-ended AI R&D. | [arXiv PDF](https://arxiv.org/pdf/2411.15114) |
| 2024 | [MLE-bench](https://arxiv.org/abs/2410.07095) | Tests agents on 75 realistic Kaggle ML engineering tasks. | [arXiv PDF](https://arxiv.org/pdf/2410.07095) |
| 2024 | [ScienceAgentBench](https://arxiv.org/abs/2410.05080) | Evaluates executable scientific programs from peer-reviewed tasks and highlights low end-to-end reliability. | [arXiv PDF](https://arxiv.org/pdf/2410.05080) |
| 2024 | [CORE-Bench](https://arxiv.org/abs/2409.11363) | Makes computational reproducibility a first-class agent task. | [arXiv PDF](https://arxiv.org/pdf/2409.11363) |
| 2023 | [MLAgentBench](https://arxiv.org/abs/2310.03302) | Foundational benchmark for iterative ML experimentation with file and execution tools. | [arXiv PDF](https://arxiv.org/pdf/2310.03302) |

## Memory and budget allocation

| Year | Work | Why it matters here | Source |
|---|---|---|---|
| 2026 | [AMA-Bench](https://arxiv.org/abs/2602.22769) | Finds similarity-only memory lossy and proposes causal graphs plus tool-augmented retrieval. | [arXiv PDF](https://arxiv.org/pdf/2602.22769) |
| 2025 | [MemoryAgentBench](https://arxiv.org/abs/2507.05257) | Decomposes memory into retrieval, test-time learning, long-range understanding, and selective forgetting. | [arXiv PDF](https://arxiv.org/pdf/2507.05257) |
| 2018 | [BOHB](https://arxiv.org/abs/1807.01774) | Combines model-based search with Hyperband-style multi-fidelity allocation. | [arXiv PDF](https://arxiv.org/pdf/1807.01774) |
| 2016 | [Hyperband](https://arxiv.org/abs/1603.06560) | Establishes successive halving and early stopping for allocating limited resources. | [arXiv PDF](https://arxiv.org/pdf/1603.06560) |

## Additional primary reports consulted

- [Google Research: AI co-scientist](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)
- [Google Research: Empirical Research Assistance](https://research.google/blog/empirical-research-assistance-era-from-nature-publication-to-catalyzing-computational-discovery/)
- [Nature: An AI system to help scientists write expert-level empirical software](https://www.nature.com/articles/s41586-026-10658-6)
- [Nature: Towards end-to-end automation of AI research](https://www.nature.com/articles/s41586-026-10265-5)

## Scope notes

- Literature cutoff: 2026-08-19.
- The local review snapshot contains 24 papers and is approximately 130 MB;
  those PDFs are Git-ignored and the public repository retains source links.
- Results reported in the direction review are attributed to the original
  papers; recommendations for this repository are explicitly marked as project
  inferences.
