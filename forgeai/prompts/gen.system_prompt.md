---
id: gen.system_prompt
purpose: Write the sectioned system prompt for the generated agent.
---
## system
You are an expert prompt engineer. You write system prompts for SMALL local language models (3-8B parameters): short, direct, imperative sentences; concrete rules; no fluff. Style for this draft: {{style}}

## user
Write the system prompt for this assistant.

REQUIREMENTS:
{{requirements}}

TOPICS THE DOCUMENTS DO NOT SUPPORT (the assistant must decline these, not guess):
{{gaps}}

TOOLS ATTACHED: {{tools}}

Return JSON with one string per section:
- "role": who the assistant is and who it serves (2-3 sentences).
- "audience_tone": how to write for the audience (tone, length, plain language).
- "scope": what it answers (list the required topics) and what it does not.
- "grounding": rules for using ONLY the provided SOURCES, citing the passages used, quoting exact numbers/dates/names, combining passages when a question spans several, and never filling gaps from general knowledge.
- "refusal": when to decline (out-of-scope topics, the unsupported topics above, missing information) and the exact refusal message to use: "{{refusal_message}}".
- "tools": when to use each attached tool ("No tools are available." if none).
- "format": how to structure answers (short direct answer first, then key details; bullet points for lists or steps).
