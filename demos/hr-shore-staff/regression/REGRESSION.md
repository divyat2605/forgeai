# Regression report

Old run: `demos/hr-shore-staff/run`  
New documents: `demos/hr-shore-staff/docs_v2`

## Document changes

- added: none
- removed: travel_and_expense_policy.pdf
- modified: leave_and_holiday_policy.pdf, remote_work_and_conduct.pdf

## Groundability changes

- Business travel and expense claims: supported -> unsupported

## Outcome of the old eval set

| Outcome | Cases |
|---|---|
| broke | 0 |
| fixed | 0 |
| invalidated | 8 |
| unchanged-pass | 20 |
| unchanged-fail | 1 |

| Case | Kind | Before | After | Outcome | Detail |
|---|---|---|---|---|---|
| E04 | answerable | True | False | **invalidated** | What is the maximum amount a line manager can approve for a… - fact no longer in documents: line manager approves claims up to INR 50,000 |
| E08 | answerable | True | False | **invalidated** | What is the maximum percentage allowed for a travel advance? - fact no longer in documents: up to 70% of the estimated trip cost |
| E11 | answerable | True | False | **invalidated** | What happens if a shore-based employee fails to follow the … - fact no longer in documents: Failure to comply may result in the denial of reimbursement or discipl… |
| E13 | multi_doc | False | False | **unchanged-fail** | What are the rules for responding to urgent inquiries and c… - 1 missing fact(s) were in passages never retrieved |
| E14 | multi_doc | True | False | **invalidated** | Which offices are covered by the leave policy and what type… - fact no longer in documents: All domestic and international travel authorized by the company |
| E15 | multi_doc | True | False | **invalidated** | What are the requirements for requesting remote work and in… - fact no longer in documents: All international travel needs a travel request at least 21 days befor… |
| E17 | application | True | False | **invalidated** | How many days of annual leave is a permanent shore staff me… - fact no longer in documents: 24 days of annual leave per calendar year |
| E18 | application | True | False | **invalidated** | What is the daily allowance for a business trip to New York? - fact no longer in documents: USD 60 per day for international travel |
| E24 | edge | True | False | **invalidated** | I need to know the highest amount I can approve for an expe… - fact no longer in documents: line manager approves claims up to INR 50,000 |

Invalidated cases are stale tests, not agent failures: regenerate the eval set for the new documents (`forge build`) to replace them.
