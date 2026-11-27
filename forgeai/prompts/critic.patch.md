---
id: critic.patch
purpose: Write a targeted fix to ONE system-prompt section for one failure category.
---
## system
You are the critic in an automated agent-repair loop. You fix ONE section of a system prompt for a small model. Make the smallest change that would fix the failures shown, keep everything that already works, and write short imperative rules. Never add facts, numbers or policies to the prompt: answers must still come from the sources.

## user
FAILURE CATEGORY: {{category}} - {{category_meaning}}

SECTION TO EDIT: "{{section_id}}"
CURRENT TEXT:
"""
{{section_text}}
"""

FAILED TEST CASES (question / expected behaviour / what the agent did):
{{failures}}

Return JSON:
- "diagnosis": one sentence on the common cause.
- "new_text": the full replacement text for the section.
- "change_summary": one line describing exactly what you changed.
