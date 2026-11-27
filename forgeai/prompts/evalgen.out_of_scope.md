---
id: evalgen.out_of_scope
purpose: Generate near-miss questions that the assistant must refuse.
---
## system
You write tricky test questions that an assistant MUST decline. Good ones look close to its domain but are not answerable from its documents or are explicitly out of scope.

## user
ASSISTANT: {{summary}}
DOCUMENTS COVER: {{covered}}
MUST REFUSE: {{must_refuse}}
NOT COVERED BY DOCUMENTS: {{gaps}}

Write {{n}} questions a real user of this assistant might ask that it must refuse. Mix: (a) questions on the must-refuse topics, (b) questions on topics adjacent to the documents but not in them, (c) one general-knowledge question unrelated to the domain.

Return JSON with "questions": list of {"question", "why_refuse"}.
