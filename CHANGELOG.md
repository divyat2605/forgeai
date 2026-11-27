# Changelog

All notable changes to ForgeAI. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-27

### Added
- **Factory pipeline**: intake interviewer (at most five questions, recorded answer sources, optional human checkpoint), groundability guard with verbatim-verified evidence and a stop below 25% coverage, a generator for declarative `forgeai.agent/1` definitions, a self-checking eval generator, a bias-defended judge, a critic–optimizer with gated, targeted patches (at most 3 iterations), and an honest report that leads with the holdout score.
- **Eval kinds**: answerable, multi-document, rule application with a verified trap value, re-phrased edge cases, tool, out-of-scope, must-refuse and gap probes. Self-checks: verbatim facts, informative-fact and vague-question filters, closed-book leakage probe, refusal labels confirmed by two model families, dedupe, and a dev/holdout split that keeps paraphrases with their source.
- **Judge**: deterministic checks first, then pointwise model checks with quote or anchor verification, failure categories that are measured rather than guessed, and a canary audit of the judge in every run.
- **Runtime and tools**: a generic runner shared by chat and evaluation; csv_lookup, a safe calculator, open-meteo weather and current_date, each gated by preconditions and evidenced need, with unused tools pruned.
- **CLI**: `build`, `chat`, `eval`, `replay`, `regress`, `doctor`, `ui`.
- **ForgeAI Studio**: a zero-dependency web app with a live factory map, report, case explorer, chat with citations, a "How it works" explainer, and the `.brief` presentation deck.
- **Evidence**: two complete demo runs with replay caches, a factory-vs-human baseline, a regression demo, a benchmark on five unseen briefs, and a measured model selection.
- **Portability**: Windows, macOS and Linux; Python 3.10+; two runtime dependencies; setup scripts; CI on all three operating systems.

### Fixed during development (found by the factory's own checks)
- Replay now compares artifacts with only timing fields excluded, and restores interview answers with their sources.
- Run folders are cleared of artifacts from earlier runs.
- Ties between critic failure categories are broken deterministically, so a run and its replay send the critic the same prompt.
- Live-data topics such as weather are tool-backed rather than treated as gaps, and table-row evidence attaches csv_lookup.
