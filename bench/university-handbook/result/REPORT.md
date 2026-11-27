# ForgeAI report: DataScienceHelper

> **Brief.** Make a student assistant for the MSc Data Science programme handbook. Students ask about assessment and grading, attendance, coursework deadlines and extensions, exams, and academic misconduct. It should also help them choose which elective courses to take next semester based on their career goals.

## Headline

| | Baseline (iteration 0) | Final agent |
|---|---|---|
| **Holdout** (never seen by the optimizer) | 8/11 (73%, CI 43-90%) | **8/11 (73%, CI 43-90%)** |
| Dev (used to choose fixes) | 13/18 (72%, CI 49-88%) | 13/18 (72%, CI 49-88%) |
| All cases | 21/29 (72%, CI 54-85%) | 21/29 (72%, CI 54-85%) |

The holdout score is the number to trust. Dev minus holdout is -1 points - no sign that the fixes over-fitted the dev cases.
With 11 holdout cases the 95% interval is wide; treat differences under ~23 points as noise.

## What still fails, and why

- **prompt defect - 6 case(s).** The right passage was retrieved but the agent's behaviour was wrong (incomplete, uncited, answered something it should refuse, or did not use its tool).
- **retrieval miss - 1 case(s).** The passage with the answer was never retrieved, so the model could not see it.
- **hallucination - 1 case(s).** The answer states things that are not in any source the agent saw.

| Case | Split | Kind | Category | Question | What happened |
|---|---|---|---|---|---|
| E01 | dev | answerable | prompt_defect | What percentage of a module is assessed by coursework? | evidence retrieved but key fact(s) missing: each module is assessed 40% by coursework and 60% by examination <br>*answered: 40% of a module is assessed by coursework.* |
| E13 | holdout | multi_doc | retrieval_miss | What happens if I submit coursework more than five days late? | 1 missing fact(s) were in passages never retrieved <br>*answered: If you submit coursework more than five days late, it will receive a mark of zero. Work s…* |
| E14 | dev | multi_doc | prompt_defect | What are the rules for handling electronic devices during exams and the deadlin… | evidence retrieved but key fact(s) missing: These items must be switched off and stored in designated areas o… <br>*answered: For electronic devices during exams, only Casio FX-83 and FX-85 calculators are allowed. …* |
| E15 | dev | multi_doc | prompt_defect | What are the consequences of failing to meet the module pass mark and committin… | evidence retrieved but key fact(s) missing: The module pass mark is 50% <br>*answered: Failing to meet the module pass mark results in a fail grade, which may affect your progr…* |
| E17 | holdout | application | prompt_defect | If a student submits coursework 3 days late, how many percentage points are ded… | evidence retrieved but key fact(s) missing: a deduction of 5 percentage points per day <br>*answered: If a student submits coursework 3 days late, a deduction of 15 percentage points is appli…* |
| E18 | holdout | application | hallucination | A student arrives 25 minutes after the exam is scheduled to start. Can they sti… | Arriving 25 minutes late still exceeds the 15-minute grace period allowed for late arrivals. <br>*answered: No, the student cannot enter. According to [C1], no entry is permitted after 30 minutes o…* |
| E21 | dev | tool | prompt_defect | What is today's date? | expected a current_date call <br>*answered: I encountered an error retrieving today's date. Please try again later or check with the …* |
| E22 | dev | edge | prompt_defect | what percetage of a modual is assed by courserwork | evidence retrieved but key fact(s) missing: each module is assessed 40% by coursework and 60% by examination <br>*answered: Coursework makes up 40% of a module's assessment.* |

**Known gaps (flagged before generation).** The brief asks for these, but the documents do not support them. The agent is instructed to decline them, and the eval set tests that it does:

- elective course selection: The documents do not provide any information about elective course selection, how students choose electives, or how career goals and program requirements influence elective choices. The passages only discuss assessment strategies, grading scales, and academic misconduct, which are unrelated to the topic of elective course selection.

## Per-iteration scorecard

| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |
|---|---|---|---|---|---|---|---|---|
| 0 | 13/18 | 8/11 | 81% | 92% | 96% | 100% | 0% | baseline |
| 1 | - | - | - | - | - | - | - | stopped: no proposed fix improved its targeted dev cases |

Failure categories by iteration (all cases):

| Iter | retrieval_miss | prompt_defect | hallucination | wrong_refusal |
|---|---|---|---|---|
| 0 | 1 | 6 | 1 | 0 |

## Every change the optimizer tried

- **P1.1** `section:grounding` for *prompt_defect* (addresses E01, E14, E15, E22): Added a rule to ensure all parts of multi-part questions are addressed with full citations.  
  Why: The agent is citing passages but not combining them to fully answer multi-part questions, leading to incomplete responses.  
  Gate: fixed 0, broke 0 -> **rejected**; iteration 1 stopped: no proposed fix improved its targeted dev cases.
- **P1.2** `section:tools` for *prompt_defect* (addresses E21): Removed the incorrect 'No tools are available.' line and kept only the current_date tool description.  
  Why: The agent incorrectly reported an error when it should have used the current_date tool.  
  Gate: fixed 0, broke 0 -> **rejected**; iteration 1 stopped: no proposed fix improved its targeted dev cases.

Full before/after text of each change: `07_changes.jsonl`.

## The agent that was built

- Definition: `agent/agent.json` (fingerprint `a2bb2e0835a2`, version 0); run it with `forge chat <this run folder>`.
- Model: `qwen3:8b`, temperature 0.0.
- Knowledge: 3 document(s); chunking 900 chars / 120 overlap; hybrid retrieval top_k=6, bm25_weight=0.4, neighbours=0, query_rewrite=False; abstention threshold 0.0.

**Tools.**

| Tool | Attached | Model proposed | Final reason |
|---|---|---|---|
| csv_lookup | no | yes | vetoed: precondition failed (table_in_corpus) |
| calculator | no | no | The calculator is not needed for the topics covered, as they are primarily based on policy text rather than arithmetic calculations. |
| weather | no | no | The weather tool is not relevant to the topics covered, which are related to academic policies and course selection. |
| current_date | yes | yes | The current_date tool is needed to calculate deadlines, late submission penalties, and the validity of extension requests. |

Tool calls during the final evaluation: current_date: 5.

**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):

| Style | Dev | Fact recall | Grounded | Prompt chars | |
|---|---|---|---|---|---|
| rules | 13/18 | 79% | 93% | 1210 |  |
| persona | 13/18 | 79% | 93% | 1282 |  |
| procedure | 13/18 | 79% | 93% | 1125 | winner |

## The generated eval set

29 cases (18 dev / 11 holdout, stratified by kind; re-phrased cases stay in the same split as their origin). Kinds: answerable 12, application 4, edge 4, gap 1, multi_doc 4, must_refuse 2, out_of_scope 1, tool 1. 4 must be refused.

Self-checks applied while generating (cases dropped):

- key facts not found verbatim in the source passage: 1
- vague questions that only make sense next to the source: 0
- answerable without documents (closed-book leakage): 1
- 'must refuse' label contradicted by the corpus: 7
- near-duplicates: 3
- failed re-phrasings / tool cases: 0 / 0

Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).

## Can the judge be trusted?

- Judge model `gemma3:4b` (gemma) vs agent `qwen3:8b` (qwen): different families (limits self-preference).
- Fact verdicts: deterministic 18, llm+quote-verified 8, llm said yes but evidence failed verification 2. Claim verdicts: deterministic 40, llm+evidence 5, llm 2, judge-missing 1.
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

- Wall time 7.4 min; 348 model calls (51 served from cache); 217,518 fresh tokens; 0 schema repairs; 0 failed calls.
- Models: factory `qwen3:8b`, agent `qwen3:8b`, judge `gemma3:4b`, embeddings `nomic-embed-text` (backend ollama).
- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.

