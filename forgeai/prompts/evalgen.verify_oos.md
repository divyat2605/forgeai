---
id: evalgen.verify_oos
purpose: Check that a should-refuse test question is really about a topic the documents do NOT cover.
---
## system
You check test labels. A question is a valid "must refuse" test only if its TOPIC is absent from the passages. If the passages discuss the same topic - even partially, even if they do not answer every detail - the label is invalid. Be strict and literal.

## user
QUESTION: {{question}}

PASSAGES (the best matches in the assistant's documents):
{{passages}}

Do these passages discuss the topic of the QUESTION? Return JSON with "answerable": true if they discuss it (even partially), false if the topic is absent, and "quote": exact words from the passages on that topic ("" if absent).
