---
id: evalgen.verify_gap
purpose: Check that a gap-probe question (a topic the groundability audit found unsupported) really cannot be answered from the documents.
---
## system
You check test labels. Be strict and literal: the passages answer the question only if they state the specific information the question asks for. Mentioning related words is not answering.

## user
QUESTION: {{question}}

PASSAGES (the best matches in the assistant's documents):
{{passages}}

Do these passages state the information needed to answer the QUESTION? Return JSON with "answerable": true or false, and "quote": the exact words from the passages that answer it ("" if not answerable).
