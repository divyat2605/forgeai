# Groundability audit

Coverage score: **67%** (supported = 1, partial = 0.5). Verdicts were cross-checked: 0 model verdict(s) were overridden by the deterministic checks.

| Topic | Verdict | Evidence (verified quote) | Missing |
|---|---|---|---|
| Plan prices and limits | supported | monthly_price_usd: 99 `price-list#r4` | - |
| Quote calculation | supported | All pricing for the FlowDesk platform is structured on a per-user, per-month basis. `commercial-terms#1` | - |
| Refund policy | partial | For new customers, a full refund is available within 30 days of the first purchase. `commercial-terms#5` | The process for initiating a refund is not clearly described. The documents mention refund eligibili |
| Billing terms | partial | Invoices are generated automatically based on the number of active users at the time of bi `commercial-terms#1` | The documents do not explicitly describe billing cycles (e.g., monthly, annual), nor do they provide |
| SLA terms | supported | For urgent issues requiring immediate attention, 24/7 phone support is available. The serv `commercial-terms#9` | - |
| Subscription status | UNSUPPORTED | - | The documents do not provide any direct information about how to check a customer's current subscrip |

**Gaps flagged at requirements stage.** The generated agent is instructed to decline these rather than guess, and the eval set includes questions that test it does:

- Subscription status: The documents do not provide any direct information about how to check a customer's current subscription status in the billing system. They mention subscription terms, pricing, and renewal processes, but none describe the mechanism or process for checking subscription status.
