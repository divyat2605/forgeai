# ForgeAI report: FlowDesk Sales Assistant

> **Brief.** Our sales reps need an assistant that knows our FlowDesk price list and commercial terms: it should look up plan prices and limits, calculate quotes for a given number of users and months, and explain refund, billing and SLA terms. It should also check a customer's current subscription status in our billing system.

## Headline

| | Baseline (iteration 0) | Final agent |
|---|---|---|
| **Holdout** (never seen by the optimizer) | 7/8 (88%, CI 53-98%) | **7/8 (88%, CI 53-98%)** |
| Dev (used to choose fixes) | 16/18 (89%, CI 67-97%) | 17/18 (94%, CI 74-99%) |
| All cases | 23/26 (88%, CI 71-96%) | 24/26 (92%, CI 76-98%) |

The holdout score is the number to trust. Dev minus holdout is +7 points.
With 8 holdout cases the 95% interval is wide; treat differences under ~22 points as noise.

## What still fails, and why

- **prompt defect - 1 case(s).** The right passage was retrieved but the agent's behaviour was wrong (incomplete, uncited, answered something it should refuse, or did not use its tool).
- **hallucination - 1 case(s).** The answer states things that are not in any source the agent saw.

| Case | Split | Kind | Category | Question | What happened |
|---|---|---|---|---|---|
| E12 | dev | multi_doc | prompt_defect | What is the monthly cost for the Team plan and what happens after renewal? | evidence retrieved but key fact(s) missing: post-renewal funds are non-refundable under any circumstances <br>*answered: The monthly cost for the Team plan is $29. After renewal, the customer will continue on t…* |
| E17 | holdout | application | hallucination | If FlowDesk's uptime is 99.8% for a month, what is the service credit percentag… | The service credit percentage is 0.1001%. <br>*answered: The service credit percentage is 0.1001%.* |

**Known gaps (flagged before generation).** The brief asks for these, but the documents do not support them. The agent is instructed to decline them, and the eval set tests that it does:

- Subscription status: The documents do not provide any direct information about how to check a customer's current subscription status in the billing system. They mention subscription terms, pricing, and renewal processes, but none describe the mechanism or process for checking subscription status.

## Per-iteration scorecard

| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |
|---|---|---|---|---|---|---|---|---|
| 0 | 16/18 | 7/8 | 91% | 96% | 96% | 100% | 0% | baseline |
| 1 | 17/18 | 7/8 | 93% | 96% | 100% | 100% | 0% | kept |
| 2 | - | - | - | - | - | - | - | stopped: no proposed fix improved its targeted dev cases |

Failure categories by iteration (all cases):

| Iter | retrieval_miss | prompt_defect | hallucination | wrong_refusal |
|---|---|---|---|---|
| 0 | 1 | 2 | 0 | 0 |
| 1 | 0 | 1 | 1 | 0 |

## Every change the optimizer tried

- **P1.1** `retrieval` for *retrieval_miss* (addresses E14): chunking {'max_chars': 900, 'overlap': 120} -> {'max_chars': 600, 'overlap': 100}; retrieval top_k/bm25_weight/neighbours 6/0.55/0 -> 6/0.25/1 (measured recall 94% -> 100% over 60 configurations)  
  Why: dev key-fact retrieval recall 94% with current parameters  
  Gate: fixed 1, broke 0 -> **accepted**; iteration 1 kept.
- **P1.2** `section:grounding` for *prompt_defect* (addresses E12): Added explicit instruction to cite refund and non-refundable terms when applicable.  
  Why: The agent failed to extract specific non-refundable terms because the grounding instruction did not explicitly require citing refund policies.  
  Gate: fixed 0, broke 0 -> **rejected**; iteration 1 kept.
- **P2.1** `section:grounding` for *prompt_defect* (addresses E12): Added instruction to extract all specific policy details, including refund terms and pricing.  
  Why: The agent failed to extract specific refund policy details despite having the relevant passage.  
  Gate: fixed 0, broke 0 -> **rejected**; iteration 2 stopped: no proposed fix improved its targeted dev cases.

Full before/after text of each change: `07_changes.jsonl`.

## The agent that was built

- Definition: `agent/agent.json` (fingerprint `6ed088fd8724`, version 1); run it with `forge chat <this run folder>`.
- Model: `qwen3:8b`, temperature 0.0.
- Knowledge: 2 document(s); chunking 600 chars / 100 overlap; hybrid retrieval top_k=6, bm25_weight=0.25, neighbours=1, query_rewrite=False; abstention threshold 0.0.

**Tools.**

| Tool | Attached | Model proposed | Final reason |
|---|---|---|---|
| csv_lookup | yes | yes | added: supported topic(s) Plan prices and limits, Quote calculation are answered by table rows; exact lookup needed |
| calculator | yes | yes | The calculator is needed to perform arithmetic operations for total cost calculations. |
| weather | no | no | The weather tool is not relevant to the scope of the FlowDesk Sales Assistant. |
| current_date | no | no | The current_date tool is not relevant to the scope of the FlowDesk Sales Assistant. |

Tool calls during the final evaluation: csv_lookup: 11, calculator: 2.

**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):

| Style | Dev | Fact recall | Grounded | Prompt chars | |
|---|---|---|---|---|---|
| rules | 16/18 | 93% | 100% | 1194 | winner |
| persona | 16/18 | 93% | 100% | 1410 |  |
| procedure | 16/18 | 93% | 100% | 1251 |  |

## The generated eval set

26 cases (18 dev / 8 holdout, stratified by kind; re-phrased cases stay in the same split as their origin). Kinds: answerable 11, application 2, edge 4, gap 1, multi_doc 4, must_refuse 2, out_of_scope 1, tool 1. 4 must be refused.

Self-checks applied while generating (cases dropped):

- key facts not found verbatim in the source passage: 1
- vague questions that only make sense next to the source: 0
- answerable without documents (closed-book leakage): 0
- 'must refuse' label contradicted by the corpus: 6
- near-duplicates: 3
- failed re-phrasings / tool cases: 0 / 1

Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).

## Can the judge be trusted?

- Judge model `gemma3:4b` (gemma) vs agent `qwen3:8b` (qwen): different families (limits self-preference).
- Fact verdicts: llm+quote-verified 13, deterministic 12, llm 1. Claim verdicts: deterministic 28, llm+evidence 5, llm 1.
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

- Small samples: 26 cases in total. Intervals are reported, and no claim here is stronger than they allow.
- The eval set is generated by the same factory that built the agent. Verbatim fact checks, the leakage probe and label verification reduce this circularity, but they do not remove it. A human-written test set would be a stronger check.
- Faithfulness checks compare each claim with the passages the agent saw. Correct general knowledge that is not in the sources is counted as unsupported, which is deliberate for a grounded agent.
- Near-miss out-of-scope tests are the hardest to label: a question can be partly covered by the documents. Two model families must agree a topic is absent before such a test is kept, but a few labels may still be debatable; each is inspectable in `05_evalset.json` (`label_votes`).
- Weather and date cases check that the tool was called, not the live values.

## Cost and reproducibility

- Wall time 5.5 min; 408 model calls (211 served from cache); 228,632 fresh tokens; 3 schema repairs; 1 failed calls.
- Models: factory `qwen3:8b`, agent `qwen3:8b`, judge `gemma3:4b`, embeddings `nomic-embed-text` (backend ollama).
- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.

