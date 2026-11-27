---
id: evalgen.application
purpose: Generate a rule-application test - a concrete situation where a condition in the passage decides which value applies.
---
## system
You write hard, realistic test questions for an assistant used by: {{audience}}. The best tests describe a user's concrete situation, where the passage gives DIFFERENT values for different conditions (city type, distance, amount band, employment status, supplier, region...) and the user's situation decides which one applies. A careless reader would quote the wrong value.

## user
PASSAGE ({{source}}):
"""
{{passage}}
"""

If this passage has a rule whose value depends on a condition, write one question that describes a specific situation (do not name the condition's category outright - e.g. name the city, the distance, the amount, the status) so that answering requires applying the condition. If it has no such conditional rule, return "applicable": false.

Return JSON:
- "applicable": true or false.
- "question": the user's question ("" if not applicable).
- "answer_span": the span COPIED EXACTLY from the passage (2-12 words) holding the value that applies to this situation.
- "trap_span": the span COPIED EXACTLY from the passage holding the value that does NOT apply but a careless reader might give.
- "condition": one sentence explaining why the answer_span applies.
