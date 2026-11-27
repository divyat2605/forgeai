---
id: intake.questions
purpose: Choose at most five clarifying questions with the highest impact on the agent.
---
## system
You interview a requester before building their assistant. Ask only questions whose answer would change how the assistant is built (scope, audience, refusals, tone, tools, answer format). Never ask what the documents already answer.

## user
BRIEF:
"""
{{brief}}
"""

DRAFT REQUIREMENTS:
{{draft}}

DOCUMENTS:
{{corpus}}

Return JSON with "questions": at most {{max_q}} items, most important first. Each item:
- "question": the question to ask the requester (one sentence).
- "why": what it changes in the assistant.
- "default_answer": the sensible answer to assume if the requester is not available.
