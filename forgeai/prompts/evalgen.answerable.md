---
id: evalgen.answerable
purpose: Generate a realistic answerable question from one passage, with the verbatim span that answers it.
---
## system
You write test questions for an assistant used by: {{audience}}. A good question asks about ONE specific rule, number, limit, deadline, entitlement, contact or step, sounds like a real user, makes sense on its own (it names its topic), and is answered by a short span of the passage.

## user
PASSAGE ({{source}}):
"""
{{passage}}
"""

Write one question a real user would ask that this passage answers. If the passage is about a specific supplier, product, part, office, policy or person, NAME it in the question (other documents may give different values for others). Never ask about the purpose, scope or introduction of a document. Never say "the passage", "this policy" or "this document".

Return JSON:
- "question": the user's question.
- "answer": the correct answer in one sentence.
- "answer_span": the shortest span COPIED EXACTLY from the passage (3-15 words) that answers the question. It must contain the key number, name or rule.
