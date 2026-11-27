# Groundability audit

Coverage score: **67%** (supported = 1, partial = 0.5). Verdicts were cross-checked: 1 model verdict(s) were overridden by the deterministic checks.

| Topic | Verdict | Evidence (verified quote) | Missing |
|---|---|---|---|
| Part details | supported | part_no: MA-1021 `spares-catalogue#r3` | - |
| Order total calculation | partial | The supplier offers a structured delivery charge policy based on the total value of the pu `supplier-terms-sup-01-harbourlin#6` | The documents do not specify how discounts are applied or calculated, nor do they provide a clear me |
| Supplier terms | partial | Free delivery to the vessel for orders above USD 2,500 is provided as a standard benefit. `supplier-terms-sup-01-harbourlin#6` | The documents do not specify the free-delivery limits for the part's supplier. They mention USD 2,50 |
| Approval rules | supported | Above USD 10,000: High-value procurement requires final approval from the Fleet Director. `purchasing-policy#8` | - |
| Weather outlook | tool | tool: weather | The documents do not provide any specific information about weather conditions or forecasts for the  |
| Shipment tracking | UNSUPPORTED | - | The documents do not provide any information about tracking the live status of shipments in transit. |

**Gaps flagged at requirements stage.** The generated agent is instructed to decline these rather than guess, and the eval set includes questions that test it does:

- Shipment tracking: The documents do not provide any information about tracking the live status of shipments in transit. They only discuss order placement, delivery charges, and logistical planning, but no mention is made of tracking systems, real-time updates, or status monitoring tools.
