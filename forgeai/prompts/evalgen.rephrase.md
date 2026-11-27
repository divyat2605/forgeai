---
id: evalgen.rephrase
purpose: Rewrite a question the way a hurried real user would (edge case).
---
## system
You rewrite questions to stress-test an assistant. Keep the meaning and the expected answer identical.

## user
ORIGINAL QUESTION: {{question}}

Rewrite it as a {{mode}}. Keep the same intent and answer. Return JSON with "question".
