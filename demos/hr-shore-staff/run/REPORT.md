# ForgeAI report: Kestrel HR Assistant

> **Brief.** I need an assistant that answers HR policy questions for the shore staff at Kestrel Shipmanagement: leave and holidays, business travel and expense claims, remote working, and conduct rules such as gifts and conflicts of interest. It should also help staff with payroll and income-tax deduction questions and with health insurance claims. Staff are office employees in Mumbai and Chennai, many of th…

## Headline

| | Baseline (iteration 0) | Final agent |
|---|---|---|
| **Holdout** (never seen by the optimizer) | 13/13 (100%, CI 77-100%) | **12/13 (92%, CI 67-99%)** |
| Dev (used to choose fixes) | 14/16 (88%, CI 64-96%) | 16/16 (100%, CI 81-100%) |
| All cases | 27/29 (93%, CI 78-98%) | 28/29 (97%, CI 83-99%) |

The holdout score is the number to trust. Dev minus holdout is +8 points.
Note the trade-off: the accepted changes fixed +2 dev case(s) but the holdout moved by -1. The holdout was never used to decide, so this is reported, not tuned away.
With 13 holdout cases the 95% interval is wide; treat differences under ~16 points as noise.

## What still fails, and why

- **retrieval miss - 1 case(s).** The passage with the answer was never retrieved, so the model could not see it.

| Case | Split | Kind | Category | Question | What happened |
|---|---|---|---|---|---|
| E13 | holdout | multi_doc | retrieval_miss | What are the rules for responding to urgent inquiries and contacting HRBP for l… | 1 missing fact(s) were in passages never retrieved <br>*answered: For urgent leave inquiries or issues, contact your HRBP. For urgent matters outside of bu…* |

**Known gaps (flagged before generation).** The brief asks for these, but the documents do not support them. The agent is instructed to decline them, and the eval set tests that it does:

- Payroll and income-tax deductions: The documents do not provide information about payroll processes or income-tax deductions. They only mention payroll-related allowances (such as internet reimbursement) but do not explain how income-tax deductions are calculated, withheld, or reported.
- Health insurance claims: The documents do not provide any information about the process of submitting health insurance claims, including how to submit claims, required documentation, approval workflows, or any related policies. The retrieved passages only cover travel and expense claims, sick leave, and leave requests, which are unrelated to health insurance claims.

## Per-iteration scorecard

| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |
|---|---|---|---|---|---|---|---|---|
| 0 | 14/16 | 13/13 | 94% | 96% | 96% | 100% | 0% | baseline |
| 1 | 16/16 | 12/13 | 98% | 100% | 96% | 100% | 0% | kept |

Failure categories by iteration (all cases):

| Iter | retrieval_miss | prompt_defect | hallucination | wrong_refusal |
|---|---|---|---|---|
| 0 | 1 | 1 | 0 | 0 |
| 1 | 1 | 0 | 0 | 0 |

## Every change the optimizer tried

- **P1.1** `retrieval` for *retrieval_miss* (addresses E12): chunking {'max_chars': 700, 'overlap': 120} -> {'max_chars': 600, 'overlap': 100}; retrieval top_k/bm25_weight/neighbours 6/0.4/0 -> 6/0.25/1 (measured recall 93% -> 100% over 64 configurations)  
  Why: dev key-fact retrieval recall 93% with current parameters  
  Gate: fixed 1, broke 0 -> **accepted**; iteration 1 kept.
- **P1.2** `section:grounding` for *prompt_defect* (addresses E14): Added instruction to ensure all relevant details, including full scope of coverage, are included.  
  Why: The agent failed to include the full scope of travel covered by the expense policy, likely due to incomplete passage combination.  
  Gate: fixed 0, broke 0 -> **rejected**; iteration 1 kept.

Full before/after text of each change: `07_changes.jsonl`.

## The agent that was built

- Definition: `agent/agent.json` (fingerprint `b3cd74f8524a`, version 1); run it with `forge chat <this run folder>`.
- Model: `qwen3:8b`, temperature 0.0.
- Knowledge: 3 document(s); chunking 600 chars / 100 overlap; hybrid retrieval top_k=6, bm25_weight=0.25, neighbours=1, query_rewrite=False; abstention threshold 0.0.

**Tools.**

| Tool | Attached | Model proposed | Final reason |
|---|---|---|---|
| csv_lookup | no | no | The tool is unavailable as the precondition is not met. |
| calculator | no | yes | vetoed: the topic it would serve ('Payroll and income-tax deductions') is a groundability gap the agent must decline |
| weather | no | no | The weather tool is not relevant to the HR policy topics outlined in the requirements. |
| current_date | no | yes | vetoed: no supported requirement mentions a need this tool serves |

**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):

| Style | Dev | Fact recall | Grounded | Prompt chars | |
|---|---|---|---|---|---|
| rules | 13/16 | 81% | 92% | 1386 |  |
| persona | 14/16 | 88% | 92% | 1470 | winner |
| procedure | 13/16 | 81% | 92% | 1440 |  |

## The generated eval set

29 cases (16 dev / 13 holdout, stratified by kind; re-phrased cases stay in the same split as their origin). Kinds: answerable 12, application 4, edge 4, gap 2, multi_doc 4, must_refuse 3. 5 must be refused.

Self-checks applied while generating (cases dropped):

- key facts not found verbatim in the source passage: 3
- vague questions that only make sense next to the source: 0
- answerable without documents (closed-book leakage): 5
- 'must refuse' label contradicted by the corpus: 6
- near-duplicates: 0
- failed re-phrasings / tool cases: 0 / 0

Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).

## Can the judge be trusted?

- Judge model `gemma3:4b` (gemma) vs agent `qwen3:8b` (qwen): different families (limits self-preference).
- Fact verdicts: deterministic 16, llm+quote-verified 10, llm said yes but evidence failed verification 1, llm+lexical-support (quote not verbatim) 1. Claim verdicts: deterministic 27, llm+evidence 5.
- Position bias: not applicable by design (all judgements are pointwise).

Canary audit: the judge scored answers whose correct verdict is known:

| Canary | Judge accuracy |
|---|---|
| correct answer accepted | 100% |
| wrong numbers / swapped facts rejected | 100% |
| same correct answer padded with filler still accepted (verbosity) | 100% |
| fabricated extra claim caught | 100% |
| **overall (24 canaries)** | **100%** |

Verbosity effect (padded minus plain acceptance): +0 points.

## Limits of this evidence

- Small samples: 29 cases in total. Intervals are reported, and no claim here is stronger than they allow.
- The eval set is generated by the same factory that built the agent. Verbatim fact checks, the leakage probe and label verification reduce this circularity, but they do not remove it. A human-written test set would be a stronger check.
- Faithfulness checks compare each claim with the passages the agent saw. Correct general knowledge that is not in the sources is counted as unsupported, which is deliberate for a grounded agent.
- Near-miss out-of-scope tests are the hardest to label: a question can be partly covered by the documents. Two model families must agree a topic is absent before such a test is kept, but a few labels may still be debatable; each is inspectable in `05_evalset.json` (`label_votes`).
- Weather and date cases check that the tool was called, not the live values.

## Cost and reproducibility

- Wall time 0.0 min; 346 model calls (346 served from cache); 0 fresh tokens; 0 schema repairs; 0 failed calls.
- Models: factory `qwen3:8b`, agent `qwen3:8b`, judge `gemma3:4b`, embeddings `nomic-embed-text` (backend ollama).
- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.

