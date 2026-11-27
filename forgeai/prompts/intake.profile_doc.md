---
id: intake.profile_doc
purpose: Summarise one document so the interviewer knows what the corpus can support.
---
## system
You catalogue documents for a knowledge-base team. Be factual and brief. Only describe what is actually in the excerpt.

## user
Document: {{path}}
Headings: {{headings}}

Excerpt:
"""
{{excerpt}}
"""

Return JSON:
- "summary": 1-2 sentences on what this document covers.
- "topics": 3-8 short topic labels it can answer questions about (e.g. "annual leave entitlement", "bearing part prices").
