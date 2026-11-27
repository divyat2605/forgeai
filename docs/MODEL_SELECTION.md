# Choosing the models: measured, not assumed

The profiles in `forgeai/config.py` were chosen by re-running one fixed artifact, the 32-case HR eval set and its winning agent definition, with different agent and judge models (`forge eval RUN --agent-model A --judge-model J`).

| Agent | Judge | Dev (18) | Holdout (14) | All (32) | Hallucination failures |
|---|---|---|---|---|---|
| **qwen3:8b** | gemma3:4b | 16 | **12** | **28** | **0** |
| qwen3:4b | gemma3:4b | 16 | 11 | 27 | 2 |
| qwen3:4b | qwen3:8b | 16 | 11 | 27 | 2 |
| gemma3:4b | qwen3:8b | 17 | 9 | 26 | 2 |
| gemma3:4b | gemma3:4b | 16 | 9 | 25 | 1 |
| qwen3:1.7b | gemma3:4b | 13 | 12 | 25 | 3 |
| llama3.2:3b | qwen3:8b | 11 | 2 | 13 | 5 |

What this shows:

1. **The judge is not biased toward its own family here.** qwen3:4b scores 27/32 whether a gemma or a qwen model judges it. gemma3:4b scores 26 under a qwen judge and 25 under a gemma judge, so the gemma judge is, if anything, harder on its own family. The deterministic layer does most of the judging, so the judge model has little room to differ. We still keep the judge in a different family from the agent on principle.
2. **qwen3:8b is the best agent**: 28/32, and the only model with no hallucination failure. It becomes the `standard` agent.
3. **llama3.2:3b is not usable** as a grounded agent at this size (13/32), so it was removed from the profiles. **qwen3:1.7b is a strong tiny model** (25/32) and replaces it in `tiny`.
4. **Each profile keeps exactly three models resident** (one qwen3 model for factory and agent, the gemma3 judge, and the embedder). That matches Ollama's default `OLLAMA_MAX_LOADED_MODELS=3`. During development a four-model setup stalled once when Ollama could not load a fourth model, and a stall during a live run is not acceptable. `forge doctor` checks residency explicitly.

Caveats: this is a single eval set of 32 cases. Differences of one or two cases are within noise (the Wilson intervals overlap). The re-runs reuse the definition tuned for qwen3:4b, which slightly favours that model.
