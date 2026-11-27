# Groundability audit

Coverage score: **58%** (supported = 1, partial = 0.5). Verdicts were cross-checked: 0 model verdict(s) were overridden by the deterministic checks.

| Topic | Verdict | Evidence (verified quote) | Missing |
|---|---|---|---|
| Leave and holidays | partial | Employees are entitled to 12 days of paid sick leave per year. `leave-and-holiday-policy#7` | Parental leave details, compensatory day off rules, and public holiday compensation are not fully ex |
| Business travel and expense claims | supported | To simplify expense reporting and cover incidental costs such as meals, local transportati `travel-and-expense-policy#7` | - |
| Remote working | supported | Confirmed employees may work remotely up to 2 days per week, provided this arrangement is  `remote-work-and-conduct#3` | - |
| Conduct rules | supported | To maintain objectivity and prevent undue influence, strict guidelines govern the acceptan `remote-work-and-conduct#9` | - |
| Payroll and income-tax deductions | UNSUPPORTED | - | The documents do not provide information about payroll processes or income-tax deductions. They only |
| Health insurance claims | UNSUPPORTED | - | The documents do not provide any information about the process of submitting health insurance claims |

**Gaps flagged at requirements stage.** The generated agent is instructed to decline these rather than guess, and the eval set includes questions that test it does:

- Payroll and income-tax deductions: The documents do not provide information about payroll processes or income-tax deductions. They only mention payroll-related allowances (such as internet reimbursement) but do not explain how income-tax deductions are calculated, withheld, or reported.
- Health insurance claims: The documents do not provide any information about the process of submitting health insurance claims, including how to submit claims, required documentation, approval workflows, or any related policies. The retrieved passages only cover travel and expense claims, sick leave, and leave requests, which are unrelated to health insurance claims.
