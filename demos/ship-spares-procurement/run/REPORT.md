# ForgeAI report: FleetSpares

> **Brief.** I need an assistant for our fleet purchasing team that finds spare parts in our spares catalogue and tells buyers the price, stock on hand, lead time and supplier for a part; works out order totals for a given quantity; explains which supplier terms apply (payment, delivery ports, warranty, free-delivery limits) and which approval rules apply to a purchase; and gives the weather outlook at the de…

## Headline

| | Baseline (iteration 0) | Final agent |
|---|---|---|
| **Holdout** (never seen by the optimizer) | 11/13 (85%, CI 58-96%) | **11/13 (85%, CI 58-96%)** |
| Dev (used to choose fixes) | 15/17 (88%, CI 66-97%) | 15/17 (88%, CI 66-97%) |
| All cases | 26/30 (87%, CI 70-95%) | 26/30 (87%, CI 70-95%) |

The holdout score is the number to trust. Dev minus holdout is +4 points - no sign that the fixes over-fitted the dev cases.
With 13 holdout cases the 95% interval is wide; treat differences under ~19 points as noise.

## What still fails, and why

- **prompt defect - 3 case(s).** The right passage was retrieved but the agent's behaviour was wrong (incomplete, uncited, answered something it should refuse, or did not use its tool).
- **hallucination - 1 case(s).** The answer states things that are not in any source the agent saw.

| Case | Split | Kind | Category | Question | What happened |
|---|---|---|---|---|---|
| E12 | holdout | multi_doc | prompt_defect | What are the approval requirements and confirmation deadlines for a USD 15,000 … | evidence retrieved but key fact(s) missing: Above USD 10,000: High-value procurement requires final approval … <br>*answered: For a USD 15,000 part order, the approval requirements are as follows:   - **Approval**: …* |
| E14 | dev | multi_doc | prompt_defect | What are the payment deadlines for invoices under the two supplier terms? | evidence retrieved but key fact(s) missing: Invoices must be paid in full within this period <br>*answered: The payment deadlines for invoices under the two supplier terms are as follows: For suppl…* |
| E20 | holdout | tool | prompt_defect | What is the total cost of purchasing the minimum order quantity of the Starting… | evidence retrieved but key fact(s) missing: 15025 <br>*answered: The total cost of purchasing the minimum order quantity of the Starting air valve is USD …* |
| E21 | dev | tool | hallucination | What is the weather forecast for Fujairah for the next two days? | Wind speeds are expected to be below 15 km/h, with the highest wind on the first day at 14.5 km/h and decreas… <br>*answered: The weather forecast for Fujairah over the next two days shows no rainfall with temperatu…* |

**Known gaps (flagged before generation).** The brief asks for these, but the documents do not support them. The agent is instructed to decline them, and the eval set tests that it does:

- Shipment tracking: The documents do not provide any information about tracking the live status of shipments in transit. They only discuss order placement, delivery charges, and logistical planning, but no mention is made of tracking systems, real-time updates, or status monitoring tools.

## Per-iteration scorecard

| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |
|---|---|---|---|---|---|---|---|---|
| 0 | 15/17 | 11/13 | 92% | 96% | 100% | 100% | 0% | baseline |
| 1 | - | - | - | - | - | - | - | stopped: no proposed fix improved its targeted dev cases |

Failure categories by iteration (all cases):

| Iter | retrieval_miss | prompt_defect | hallucination | wrong_refusal |
|---|---|---|---|---|
| 0 | 0 | 3 | 1 | 0 |

## Every change the optimizer tried

- **P1.1** `section:grounding` for *hallucination* (addresses E14, E21): Added a rule to explicitly prohibit inferred or generalized information, requiring exact source wording.  
  Why: The agent is providing inferred or generalized information rather than strictly citing source content.  
  Gate: fixed 0, broke 1 -> **rejected**; iteration 1 stopped: no proposed fix improved its targeted dev cases.

Full before/after text of each change: `07_changes.jsonl`.

## The agent that was built

- Definition: `agent/agent.json` (fingerprint `016fe657ab28`, version 0); run it with `forge chat <this run folder>`.
- Model: `qwen3:8b`, temperature 0.0.
- Knowledge: 5 document(s); chunking 900 chars / 120 overlap; hybrid retrieval top_k=6, bm25_weight=0.55, neighbours=0, query_rewrite=False; abstention threshold 0.0.

**Tools.**

| Tool | Attached | Model proposed | Final reason |
|---|---|---|---|
| csv_lookup | yes | yes | The purchasing_policy.pdf contains approval rules based on the part's cost and quantity. |
| calculator | yes | yes | The calculator is needed to compute the total cost for a given quantity of a part, including unit price and any applicable discounts or min… |
| weather | yes | yes | The weather tool provides the weather forecast for the delivery port to help plan vessel deliveries. |
| current_date | no | no | The current_date tool is not needed for the topics covered by FleetSpares. |

Tool calls during the final evaluation: csv_lookup: 13, calculator: 2, weather: 1.

**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):

| Style | Dev | Fact recall | Grounded | Prompt chars | |
|---|---|---|---|---|---|
| rules | 14/17 | 96% | 86% | 1101 |  |
| persona | 15/17 | 96% | 93% | 1497 |  |
| procedure | 15/17 | 96% | 93% | 1214 | winner |

## The generated eval set

30 cases (17 dev / 13 holdout, stratified by kind; re-phrased cases stay in the same split as their origin). Kinds: answerable 10, application 4, edge 4, gap 1, multi_doc 4, must_refuse 4, tool 3. 5 must be refused.

Self-checks applied while generating (cases dropped):

- key facts not found verbatim in the source passage: 2
- vague questions that only make sense next to the source: 0
- answerable without documents (closed-book leakage): 1
- 'must refuse' label contradicted by the corpus: 6
- near-duplicates: 0
- failed re-phrasings / tool cases: 0 / 0

Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).

## Can the judge be trusted?

- Judge model `gemma3:4b` (gemma) vs agent `qwen3:8b` (qwen): different families (limits self-preference).
- Fact verdicts: deterministic 17, llm+quote-verified 10, llm said yes but evidence failed verification 1. Claim verdicts: deterministic 42, llm+evidence 10.
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

- Small samples: 30 cases in total. Intervals are reported, and no claim here is stronger than they allow.
- The eval set is generated by the same factory that built the agent. Verbatim fact checks, the leakage probe and label verification reduce this circularity, but they do not remove it. A human-written test set would be a stronger check.
- Faithfulness checks compare each claim with the passages the agent saw. Correct general knowledge that is not in the sources is counted as unsupported, which is deliberate for a grounded agent.
- Near-miss out-of-scope tests are the hardest to label: a question can be partly covered by the documents. Two model families must agree a topic is absent before such a test is kept, but a few labels may still be debatable; each is inspectable in `05_evalset.json` (`label_votes`).
- Weather and date cases check that the tool was called, not the live values.

## Cost and reproducibility

- Wall time 0.0 min; 344 model calls (344 served from cache); 0 fresh tokens; 0 schema repairs; 0 failed calls.
- Models: factory `qwen3:8b`, agent `qwen3:8b`, judge `gemma3:4b`, embeddings `nomic-embed-text` (backend ollama).
- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.

