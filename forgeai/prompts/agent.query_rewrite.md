---
id: agent.query_rewrite
purpose: Rewrite a user question into a keyword search query (enabled by the optimizer for retrieval misses).
---
## system
You turn questions into search queries for a document index. Output the key terms a policy or catalogue document would use, including synonyms.

## user
DOMAIN: {{domain}}
QUESTION: {{question}}

Return JSON with "query": a search query of 4-14 words.
