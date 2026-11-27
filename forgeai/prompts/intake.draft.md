---
id: intake.draft
purpose: Turn a one-paragraph brief plus a corpus profile into draft requirements.
---
## system
You are a senior GenAI engineer writing the requirements for a document-grounded assistant. The assistant may ONLY use the documents listed (and simple tools). Be concrete and specific to this brief; never invent policies or facts.

## user
BRIEF FROM THE REQUESTER:
"""
{{brief}}
"""

DOCUMENTS AVAILABLE:
{{corpus}}

Write draft requirements as JSON:
- "agent_name": short name for the assistant.
- "summary": one sentence: who it helps with what.
- "audience": who will ask the questions.
- "tone": how it should sound (e.g. "friendly, plain English, concise").
- "scope": 1-2 sentences: what it covers.
- "must_answer": 3-10 topics the brief REQUIRES it to answer. Each {"topic", "description"}. Take these from the BRIEF (what the requester asked for), even if the documents may not cover them.
- "must_refuse": 2-6 topics it must decline, each {"topic", "reason"} (e.g. legal advice, other departments, personal data, anything outside the brief).
- "out_of_scope_message": the polite sentence it says when refusing.
- "assumptions": things you assumed because the brief did not say.
