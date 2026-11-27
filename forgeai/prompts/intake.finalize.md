---
id: intake.finalize
purpose: Merge the requester's answers into final requirements.
---
## system
You finalise requirements for a document-grounded assistant. Apply the requester's answers exactly. Keep everything else from the draft unless an answer changes it.

## user
BRIEF:
"""
{{brief}}
"""

DRAFT REQUIREMENTS:
{{draft}}

INTERVIEW (question -> answer; "(default)" means the requester did not answer and the default was assumed):
{{qa}}

Return the final requirements JSON with the same fields as the draft: agent_name, summary, audience, tone, scope, must_answer, must_refuse, out_of_scope_message, assumptions. Add each defaulted answer to "assumptions".
