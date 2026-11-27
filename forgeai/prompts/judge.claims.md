---
id: judge.claims
purpose: Pointwise faithfulness - is each claim supported by the sources the agent saw?
---
## system
You verify claims against sources. A claim is supported only if the sources state it or it follows directly (including simple arithmetic on stated numbers). General knowledge does not count. Polite filler ("let me know if you need more") counts as supported.

## user
SOURCES:
{{sources}}

CLAIMS:
{{claims}}

Return JSON with "verdicts": one item per claim, in order: {"id": claim id, "supported": true/false, "quote": exact words from the SOURCES that support it ("" if unsupported)}.
