# ForgeAI architecture

```
 brief.md + docs/ ─┐
                   ▼
 [1] ingest ── PDF · DOCX · XLSX · CSV · MD · TXT · HTML · JSON ──► structure-aware chunks + contextual headers
                   │                                               hybrid index (BM25 + embeddings, RRF)
                   ▼
 [2] intake ── profile each document ─► draft requirements ─► ≤5 high-impact questions (each with a default)
                   │     answers: live terminal │ requester notes │ answers file │ stated default (source recorded)
                   │     optional human checkpoint: approve / edit requirements.json
                   ▼
 [3] groundability guard ── per required topic: retrieve ─► model verdict ─► VERIFIED: quotes must exist verbatim,
                   │        lexical cross-check, tool verdicts must name an available tool
                   │        gaps ─► explicit refusal topics;   coverage < 25 % ─► STOP (no agent built)
                   ▼
 [4] generator ── tools: model decides per tool ─► deterministic gates (precondition, need evidenced in a
                   │      SUPPORTED requirement, not serving a gap) ─► sectioned system prompt (3 styles)
                   │      ─► deterministic completion (every must-refuse topic and gap stated) ─► agent.json
                   ▼
 [5] eval generator ── answerable · multi-doc · rule application (+trap) · edge · tool · out-of-scope · must-refuse · gap
                   │   self-checks: verbatim facts (repaired or dropped) · no give-aways · closed-book leakage
                   │   probe · refusal labels verified against the corpus · dedupe · calculator re-computation
                   │   dev / holdout split, stratified, grouped by origin (no paraphrase leakage)
                   ▼
 [6] prompt tournament ── 3 candidate prompts scored on DEV, pointwise ─► winner
                   ▼
 [7] critic–optimizer (≤3 iterations)
        evaluate ─► judge (deterministic first; pointwise LLM with verified quotes) ─► failure category is
        MEASURED: fact not in retrieved text = retrieval miss · unsupported claim = hallucination ·
        refused with evidence = wrong refusal · otherwise prompt defect
        ─► targeted patches: retrieval grid search on measured recall │ query rewrite │ calibrated abstention
           threshold │ critic rewrites ONE prompt section (no new numbers allowed)
        ─► each patch gated on its target cases + regression sample ─► merge ─► full re-eval
        ─► keep only if dev strictly improves (paired, McNemar reported) · early stop on budget / low gain
        ─► tool audit: tools never used are removed if that costs no dev case
                   ▼
 [8] judge audit ── canaries with known verdicts: gold accepted · corrupted rejected · padded accepted
                   │ (verbosity) · fabricated claim caught
                   ▼
 [9] ship ── agent/agent.json + knowledge index ─► `forge chat` (same runtime as the evals)
             REPORT.md (holdout first, CIs, what still fails and why) · manifest · trace · replay cache

 Studio (`forge ui`) ── stdlib HTTP server + hand-written SPA over the run folders: live build, report,
             case explorer, chat with citations, explainer film, and the .brief deck
```

## Why the pieces are shaped this way

| Risk with small models | Design response |
|---|---|
| Model invents a quote to justify a verdict | Every quote is re-verified in code (`util/text.quote_in`), and numbers must match exactly |
| Generated eval facts are paraphrased or wrong | Facts must be verbatim spans of the source passage; repaired to the exact span or dropped |
| Eval measures memory, not grounding | Closed-book probe: questions the agent's model answers without documents are dropped |
| "Must refuse" test is actually answerable | Refusal labels verified against the corpus by a different model with a verified quote |
| Optimizer overfits its own tests | Critic sees dev failures only; holdout is reported, never used for a decision |
| A "fix" helps one case and breaks three | Per-patch regression gate + iteration-level keep/revert on paired results |
| Judge biased by position / length / own family | Pointwise only; per-fact binary checks with verified quotes; different-family judge; canary audit every run |
| Small model breaks the output format | JSON-schema constrained decoding + validation + bounded repair; the runtime contract footer cannot be patched |
| Tool sprawl | Need must be evidenced in a supported requirement; gap-serving tools vetoed; unused tools pruned empirically |
| Live demo on an unknown machine | `forge doctor`, profiles for slow machines, time budget with early stop, resumable runs, replay cache |
| "Must refuse" test is actually partly answerable | Near-miss refusal labels need two model families (judge and factory) to agree the topic is absent |
| Agent quotes the right table but the wrong row | Rule-application tests: a concrete situation picks the value, with the tempting wrong value recorded as a verified trap |
| Model judge says "stated" but quotes the fact instead of the answer | Second verification path: every anchor of the fact (numbers, acronyms, proper names) must be in the answer |
| Live data (weather, today's date) mistaken for a documentation gap | Registry capability match makes such topics tool-backed, so the right tool is attached and not vetoed |
| PDF page furniture pollutes chunks | Lines repeated on most pages (digits ignored) are removed as running headers/footers |
