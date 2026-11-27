# ForgeAI stopped: brief not groundable

The documents support only 0% of the required topics, so any agent built from them would have to invent its answers. No agent was generated.

# Groundability audit

Coverage score: **0%** (supported = 1, partial = 0.5). Verdicts were cross-checked: 0 model verdict(s) were overridden by the deterministic checks.

| Topic | Verdict | Evidence (verified quote) | Missing |
|---|---|---|---|
| Indian visa application process for seafarers | UNSUPPORTED | - | The retrieved passages only discuss galley cleaning schedules and hygiene protocols in a kitchen env |
| Immigration rules for seafarers in foreign ports | UNSUPPORTED | - | The documents retrieved do not provide any information related to immigration rules for seafarers en |
| Document checklist for Indian visa applications | UNSUPPORTED | - | The retrieved passages only discuss kitchen hygiene, cleaning schedules, and food safety protocols.  |
| Processing times for Indian visas | UNSUPPORTED | - | The documents do not provide any information about processing times for Indian visas or immigration  |
| Fees for Indian visa applications | UNSUPPORTED | - | The documents do not provide any information about fees for Indian visa applications or costs associ |

**Gaps flagged at requirements stage.** The generated agent is instructed to decline these rather than guess, and the eval set includes questions that test it does:

- Indian visa application process for seafarers: The retrieved passages only discuss galley cleaning schedules and hygiene protocols in a kitchen environment. They do not provide any information about the Indian visa application process for seafarers, including steps, requirements, documentation, or procedures related to visa applications.
- Immigration rules for seafarers in foreign ports: The documents retrieved do not provide any information related to immigration rules for seafarers entering India through foreign ports. They are focused on kitchen safety, cleaning protocols, and operational procedures, which are unrelated to immigration regulations or seafarer entry requirements.
- Document checklist for Indian visa applications: The retrieved passages only discuss kitchen hygiene, cleaning schedules, and food safety protocols. They do not provide any information about the document checklist required for Indian visa applications, particularly for seafarers.
- Processing times for Indian visas: The documents do not provide any information about processing times for Indian visas or immigration procedures related to visa applications.
- Fees for Indian visa applications: The documents do not provide any information about fees for Indian visa applications or costs associated with applying for an Indian visa for seafarers.

Add documents that cover the gaps, narrow the brief, or re-run with `--force`.
