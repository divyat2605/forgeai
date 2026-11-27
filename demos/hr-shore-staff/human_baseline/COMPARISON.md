# Factory vs human baseline (HR demo)

Same brief, documents, model (`qwen3:8b`), runtime and judge. The **only** difference is who wrote the agent definition: the factory (`demos/hr-shore-staff/run/agent/agent.json`, from one paragraph) or the developer by hand (`agent.json` in this folder). Both are scored on the factory's generated eval set.

| | Factory | Hand-written |
|---|---|---|
| All cases | 28/29 (97%, CI 83-99%) | 26/29 (90%, CI 74-96%) |
| Dev | 16/16 (100%, CI 81-100%) | 14/16 (88%, CI 64-97%) |
| Holdout | 12/13 (92%, CI 67-99%) | 12/13 (92%, CI 67-99%) |
| Hallucination failures | 0 | 0 |

Paired comparison: the hand-written agent passes 1 case(s) the factory fails and fails 3 the factory passes (exact McNemar p = 0.62).

## Where they differ

- **E13** (multi_doc, holdout) - hand-written wins. *What are the rules for responding to urgent inquiries and contacting HRBP for leave issues?*  
  Loser's failure: retrieval_miss - 1 missing fact(s) were in passages never retrieved
- **E14** (multi_doc, dev) - factory wins. *Which offices are covered by the leave policy and what type of travel is governed by the expense policy?*  
  Loser's failure: prompt_defect - evidence retrieved but key fact(s) missing: All domestic and international travel authorized by the company
- **E19** (application, dev) - factory wins. *Can a new joiner take annual leave after 2 months of service?*  
  Loser's failure: prompt_defect - evidence retrieved but key fact(s) missing: Employees may only take annual leave after completing 3 months of service
- **E27** (must_refuse, holdout) - factory wins. *How do I apply for a leave of absence for personal reasons not covered by the current leave policies?*  
  Loser's failure: prompt_defect - should refuse (out of scope) but answered from loosely related passages

## Reading

- The hand-written prompt names the three policies, lists every sub-topic and tells the agent to answer the covered part of a partly covered question: domain knowledge a careful engineer brings after reading all three documents.
- The factory produced its agent from one paragraph with no human effort, and also flagged the unsupported topics, wrote and verified the tests, and audited its own judge - none of which exists for the hand-written agent.
- Caveat: the baseline's author had seen generated cases from earlier development runs on these documents, so the comparison slightly favours the baseline.
