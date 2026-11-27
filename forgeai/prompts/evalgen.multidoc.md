---
id: evalgen.multidoc
purpose: Generate a question whose answer needs facts from two different documents.
---
## system
You write hard but realistic test questions for an assistant used by: {{audience}}. The question must need BOTH passages to answer completely, and it should be something a real user could plausibly ask in one go (for example comparing two limits, or a situation that touches both rules).

## user
PASSAGE A ({{source_a}}):
"""
{{passage_a}}
"""

PASSAGE B ({{source_b}}):
"""
{{passage_b}}
"""

Write one natural user question whose complete answer needs one specific fact from A AND one specific fact from B. Ask about specific rules, numbers, limits or deadlines - never about the purpose of a document.

Return JSON:
- "question": the user's question.
- "answer": the correct combined answer.
- "fact_a": the shortest span COPIED EXACTLY from passage A (3-15 words) that the answer needs.
- "fact_b": the shortest span COPIED EXACTLY from passage B (3-15 words) that the answer needs.
