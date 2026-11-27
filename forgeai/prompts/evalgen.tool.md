---
id: evalgen.tool
purpose: Generate a question that needs an attached tool to answer exactly.
---
## system
You write test questions for an assistant used by: {{audience}}. The question must require the tool "{{tool}}" ({{tool_desc}}) to answer exactly.

## user
DATA THE ASSISTANT CAN SEE:
"""
{{data}}
"""

Write one realistic question that needs the {{tool}} tool on this data. {{hint}}

Return JSON:
- "question": the user's question.
- "answer": the exact correct answer.
- "key_facts": 1-2 short facts the answer must contain (copy exact values from the data, or the exact computed number).
