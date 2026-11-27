"""Stage 2 - Groundability guard.

For every topic the brief requires, retrieve evidence and ask the model for a
verdict - but never take the verdict on trust:

* "supported" needs at least one evidence quote that is verified VERBATIM in
  the retrieved passages (fuzzy-tolerant); otherwise it is downgraded.
* a lexical cross-check measures how much of the topic's vocabulary exists in
  the corpus at all; a "supported" verdict on vocabulary the corpus never uses
  is downgraded to "partial" and flagged as a judge disagreement.
* "tool" verdicts must name a registry tool whose preconditions hold.

Gaps (unsupported topics) become explicit refusal topics in the agent and lead
the final report. If almost nothing is groundable the factory stops instead of
building an agent that would hallucinate the gap away.
"""

from __future__ import annotations

from forgeai.factory.context import Run
from forgeai.llm.gateway import LLMError
from forgeai.llm.schema import STR, arr, enum, obj
from forgeai.runtime.tools import REGISTRY
from forgeai.util.io import write_json
from forgeai.util.text import content_tokens, quote_in

VERDICT_SCHEMA = obj({
    "verdict": enum("supported", "partial", "tool", "unsupported"),
    "evidence_quotes": arr(STR, 0, 3),
    "tool": STR,
    "missing": STR,
})


def tool_preconditions(run: Run) -> dict[str, bool]:
    has_table = any(d.table is not None for d in run.docs)
    return {name: (spec.requires != "table_in_corpus" or has_table) and
            not (spec.network and run.settings.offline_tools)
            for name, spec in REGISTRY.items()}


def check(run: Run) -> dict:
    assert run.index is not None
    vocab = set()
    for c in run.chunks:
        vocab.update(content_tokens(c.indexed_text))
    ok_tools = tool_preconditions(run)
    tool_txt = "\n".join(f"- {n}: {s.description}" for n, s in REGISTRY.items() if ok_tools[n])

    def one(t: dict) -> dict:
        query = f"{t['topic']}. {t.get('description', '')}"
        hits = run.index.search(query, top_k=5, bm25_weight=0.4, gateway=run.gw)
        passages = "\n\n".join(f"[{h.chunk.chunk_id}] {h.chunk.text[:900]}" for h in hits) or "(none)"
        try:
            v = run.gw.run_prompt("factory", "ground.topic", VERDICT_SCHEMA, stage="groundability",
                                  topic=t["topic"], description=t.get("description", ""), passages=passages,
                                  tools=tool_txt or "(none)")
        except LLMError as e:
            v = {"verdict": "partial", "evidence_quotes": [], "tool": "", "missing": f"(audit failed: {e})"}
        evidence = []
        for q in v.get("evidence_quotes", []):
            src = next((h.chunk.chunk_id for h in hits if quote_in(q, h.chunk.text)), None)
            if src:
                evidence.append({"quote": q, "chunk_id": src})
        ttoks = set(content_tokens(t["topic"] + " " + t.get("description", "")))
        lex = len(ttoks & vocab) / len(ttoks) if ttoks else 0.0
        verdict = v["verdict"]
        notes = []
        if verdict == "supported" and not evidence:
            verdict = "partial" if lex >= 0.5 else "unsupported"
            notes.append("model said supported but none of its quotes exist in the passages - downgraded")
        if verdict == "supported" and lex < 0.3:
            verdict = "partial"
            notes.append(f"topic vocabulary barely appears in corpus (lexical coverage {lex:.0%}) - downgraded")
        tool = (v.get("tool") or "").strip()
        if verdict == "tool":
            if tool not in REGISTRY or not ok_tools.get(tool):
                notes.append(f"named tool {tool!r} unavailable - treated as unsupported")
                verdict, tool = ("partial" if evidence else "unsupported"), ""
        else:
            tool = ""
        if verdict == "unsupported" and evidence:
            verdict = "partial"
            notes.append("verified evidence exists - upgraded to partial")
        # Live/external information (weather, today's date) can never be in the documents: if the topic
        # asks for it and the tool is available, the topic is tool-backed, not a gap.
        if verdict in ("unsupported", "partial") and not tool:
            import re as _re
            text = f"{t['topic']} {t.get('description', '')}".lower()
            for name, spec in REGISTRY.items():
                if spec.external_data and ok_tools.get(name) and spec.live_need and _re.search(spec.live_need, text):
                    notes.append(f"topic needs live data the '{name}' tool provides (registry capability match)")
                    verdict, tool = "tool", name
                    break
        return {"topic": t["topic"], "description": t.get("description", ""), "verdict": verdict,
                "model_verdict": v["verdict"], "evidence": evidence, "tool": tool,
                "missing": v.get("missing", ""), "lexical_coverage": round(lex, 2), "notes": notes,
                "retrieved": [{"chunk_id": h.chunk.chunk_id, "dense": round(h.dense, 3)} for h in hits]}

    topics = run.pmap(one, run.requirements["must_answer"], "auditing groundability")
    n = len(topics) or 1
    sup = sum(1 for t in topics if t["verdict"] in ("supported", "tool"))
    part = sum(1 for t in topics if t["verdict"] == "partial")
    result = {
        "topics": topics,
        "coverage": round((sup + 0.5 * part) / n, 3),
        "supported": [t["topic"] for t in topics if t["verdict"] == "supported"],
        "tool_backed": [{"topic": t["topic"], "tool": t["tool"]} for t in topics if t["verdict"] == "tool"],
        "partial": [{"topic": t["topic"], "missing": t["missing"]} for t in topics if t["verdict"] == "partial"],
        "gaps": [{"topic": t["topic"], "missing": t["missing"] or "no supporting passage"} for t in topics
                 if t["verdict"] == "unsupported"],
        "disagreements": sum(1 for t in topics if t["notes"]),
    }
    run.groundability = result
    write_json(run.path("03_groundability.json"), result)
    return result


def markdown(g: dict) -> str:
    L = ["# Groundability audit", "",
         f"Coverage score: **{g['coverage']:.0%}** (supported = 1, partial = 0.5). "
         f"Verdicts were cross-checked: {g['disagreements']} model verdict(s) were overridden by the deterministic checks.", "",
         "| Topic | Verdict | Evidence (verified quote) | Missing |", "|---|---|---|---|"]
    for t in g["topics"]:
        ev = t["evidence"][0]["quote"][:90] + f" `{t['evidence'][0]['chunk_id']}`" if t["evidence"] else \
            (f"tool: {t['tool']}" if t["tool"] else "-")
        verdict = t["verdict"].upper() if t["verdict"] == "unsupported" else t["verdict"]
        L.append(f"| {t['topic']} | {verdict} | {ev.replace('|', '/')} | {(t['missing'] or '-')[:100].replace('|', '/')} |")
    if g["gaps"]:
        L += ["", "**Gaps flagged at requirements stage.** The generated agent is instructed to decline these "
              "rather than guess, and the eval set includes questions that test it does:", ""]
        L += [f"- {x['topic']}: {x['missing']}" for x in g["gaps"]]
    return "\n".join(L) + "\n"
