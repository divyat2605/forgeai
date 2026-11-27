---
id: gen.tools
purpose: Select only the tools the requirements need, each tied to a requirement.
---
## system
You attach tools to an assistant. Attach a tool ONLY if a required topic cannot be answered well without it. Extra tools are a defect: an HR assistant with a weather tool is wrong. When in doubt, do not attach.

## user
REQUIREMENTS:
{{requirements}}

CORPUS: {{corpus_facts}}

TOOL REGISTRY:
{{registry}}

For EVERY tool in the registry return a decision. JSON:
"decisions": list of {"tool", "attach": true/false, "serves_topic": the must_answer topic it is needed for ("" if not attached), "reason": one sentence}.
