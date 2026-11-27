# ForgeAI report: SMS Safety Assistant

> **Brief.** Our ship officers need an assistant for our Safety Management System procedures: bunkering, enclosed space entry, and incident reporting. Officers should be able to ask what the procedure requires at each step. It should also tell them whether the weather at their next port is suitable for bunkering.

## Headline

| | Baseline (iteration 0) | Final agent |
|---|---|---|
| **Holdout** (never seen by the optimizer) | 10/10 (100%, CI 72-100%) | **10/10 (100%, CI 72-100%)** |
| Dev (used to choose fixes) | 15/18 (83%, CI 61-94%) | 15/18 (83%, CI 61-94%) |
| All cases | 25/28 (89%, CI 73-96%) | 25/28 (89%, CI 73-96%) |

The holdout score is the number to trust. Dev minus holdout is -17 points - no sign that the fixes over-fitted the dev cases.
With 10 holdout cases the 95% interval is wide; treat differences under ~14 points as noise.

## What still fails, and why

- **prompt defect - 2 case(s).** The right passage was retrieved but the agent's behaviour was wrong (incomplete, uncited, answered something it should refuse, or did not use its tool).
- **hallucination - 1 case(s).** The answer states things that are not in any source the agent saw.

| Case | Split | Kind | Category | Question | What happened |
|---|---|---|---|---|---|
| E04 | dev | answerable | prompt_defect | What must be done before starting the bunkering procedure? | evidence retrieved but key fact(s) missing: scuppers must be plugged and the SOPEP locker opened <br>*answered: Before starting the bunkering procedure, the team must conduct a thorough pre-transfer in…* |
| E15 | dev | multi_doc | prompt_defect | What are the record-keeping requirements for bunker delivery notes and enclosed… | evidence retrieved but key fact(s) missing: pretransfer checklist and bunker delivery notes are to be filed i… <br>*answered: Bunker delivery notes and enclosed space permits have specific record-keeping requirement…* |
| E25 | dev | edge | hallucination | What should I do before beginning the bunkering process on my vessel? | Finally, check the weather conditions for the next port to ensure they are suitable for bunkering. <br>*answered: Before beginning the bunkering process, you should hold a pre-bunkering safety meeting wi…* |

## Per-iteration scorecard

| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |
|---|---|---|---|---|---|---|---|---|
| 0 | 15/18 | 10/10 | 92% | 96% | 100% | 100% | 0% | baseline |
| 1 | 15/18 | 9/10 | 94% | 92% | 100% | 100% | 0% | reverted (dev did not improve after merging patches) |

Failure categories by iteration (all cases):

| Iter | retrieval_miss | prompt_defect | hallucination | wrong_refusal |
|---|---|---|---|---|
| 0 | 0 | 2 | 1 | 0 |
| 1 | 0 | 2 | 2 | 0 |

## Every change the optimizer tried

- **P1.1** `section:grounding` for *prompt_defect* (addresses E04, E15, E25): Added requirement to explicitly include all required procedural steps and specific actions in the answer.  
  Why: The agent is retrieving the right passage but failing to extract specific procedural steps and required actions from the sources.  
  Gate: fixed 1, broke 0 -> **accepted**; iteration 1 reverted (dev did not improve after merging patches).

Full before/after text of each change: `07_changes.jsonl`.

## The agent that was built

- Definition: `agent/agent.json` (fingerprint `a962190adeb6`, version 0); run it with `forge chat <this run folder>`.
- Model: `qwen3:8b`, temperature 0.0.
- Knowledge: 3 document(s); chunking 900 chars / 120 overlap; hybrid retrieval top_k=6, bm25_weight=0.4, neighbours=0, query_rewrite=False; abstention threshold 0.0.

**Tools.**

| Tool | Attached | Model proposed | Final reason |
|---|---|---|---|
| csv_lookup | no | no | The CSV lookup tool is not needed as the required procedures are described in the provided PDF documents. |
| calculator | no | no | The calculator tool is not needed as the required procedures do not involve arithmetic calculations. |
| weather | yes | yes | The weather tool is needed to check the current and forecasted weather conditions at the next port for bunkering. |
| current_date | no | no | The current date tool is not needed as the required procedures do not involve date-based calculations. |

Tool calls during the final evaluation: weather: 4.

**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):

| Style | Dev | Fact recall | Grounded | Prompt chars | |
|---|---|---|---|---|---|
| rules | 14/18 | 87% | 88% | 1196 |  |
| persona | 14/18 | 87% | 88% | 1248 |  |
| procedure | 15/18 | 87% | 94% | 1278 | winner |

## The generated eval set

28 cases (18 dev / 10 holdout, stratified by kind; re-phrased cases stay in the same split as their origin). Kinds: answerable 13, application 3, edge 4, multi_doc 4, must_refuse 2, out_of_scope 1, tool 1. 3 must be refused.

Self-checks applied while generating (cases dropped):

- key facts not found verbatim in the source passage: 1
- vague questions that only make sense next to the source: 1
- answerable without documents (closed-book leakage): 2
- 'must refuse' label contradicted by the corpus: 6
- near-duplicates: 2
- failed re-phrasings / tool cases: 0 / 0

Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).

## Can the judge be trusted?

- Judge model `gemma3:4b` (gemma) vs agent `qwen3:8b` (qwen): different families (limits self-preference).
- Fact verdicts: llm+quote-verified 13, deterministic 13, llm 2. Claim verdicts: deterministic 33, llm+evidence 3, llm 1.
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

- Small samples: 28 cases in total. Intervals are reported, and no claim here is stronger than they allow.
- The eval set is generated by the same factory that built the agent. Verbatim fact checks, the leakage probe and label verification reduce this circularity, but they do not remove it. A human-written test set would be a stronger check.
- Faithfulness checks compare each claim with the passages the agent saw. Correct general knowledge that is not in the sources is counted as unsupported, which is deliberate for a grounded agent.
- Near-miss out-of-scope tests are the hardest to label: a question can be partly covered by the documents. Two model families must agree a topic is absent before such a test is kept, but a few labels may still be debatable; each is inspectable in `05_evalset.json` (`label_votes`).
- Weather and date cases check that the tool was called, not the live values.

## Cost and reproducibility

- Wall time 6.9 min; 366 model calls (83 served from cache); 214,174 fresh tokens; 0 schema repairs; 0 failed calls.
- Models: factory `qwen3:8b`, agent `qwen3:8b`, judge `gemma3:4b`, embeddings `nomic-embed-text` (backend ollama).
- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.

