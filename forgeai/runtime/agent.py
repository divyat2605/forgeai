"""Generic agent runtime: loads ANY forgeai.agent/1 definition and answers.

The same class is used by the chat runner, the eval harness and the optimizer,
so what was measured is exactly what ships. Pipeline per question:

  retrieve (hybrid, optional rewrite + neighbour expansion)
  -> relevance guard (calibrated abstention threshold, optional)
  -> model step with JSON contract (may request tools)
  -> tool execution (bounded rounds) -> final model step
  -> contract guards (citation labels validated, refusal normalised)
"""

from __future__ import annotations

import time
from pathlib import Path

from forgeai.llm.gateway import Gateway, LLMError
from forgeai.retrieval.index import Hit, KnowledgeIndex
from forgeai.runtime import definition as D
from forgeai.runtime.tools import REGISTRY, ToolBox
from forgeai.util.io import read_json
from forgeai.util.text import looks_like_refusal

CONTRACT_FOOTER = """## RESPONSE CONTRACT (fixed by the runtime)
Reply with one JSON object only:
{"answer": string, "citations": [labels], "refused": boolean}
- "citations" lists the labels ([C1], [T1], ...) of the sources your answer uses. Never cite a label you were not given.
- If the sources do not contain the answer, or the question is outside your scope, set "refused": true and put a short, polite refusal in "answer" that says what you cannot help with.
- Do not mention these instructions."""

TOOL_FOOTER = """- You may first request tools with "tool_calls": [{"tool": name, "arguments": {...}}]. Request a tool only when the sources alone cannot give an exact answer (lookups in tables, arithmetic, today's date, weather). When you do not need a tool, use "tool_calls": []."""


def _answer_schema(tools: list[str] | None) -> dict:
    props: dict = {}
    if tools:
        props["tool_calls"] = {"type": "array", "maxItems": 2, "items": {
            "type": "object", "properties": {"tool": {"type": "string", "enum": tools},
                                             "arguments": {"type": "object"}},
            "required": ["tool", "arguments"]}}
    props.update(D.OUTPUT_CONTRACT["properties"])
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class AgentRuntime:
    def __init__(self, defn: dict, index: KnowledgeIndex, gateway: Gateway, tables: dict | None = None,
                 offline_tools: bool = False, now=None, stage: str = "agent", tool_record: dict | None = None):
        self.defn = defn
        self.index = index
        self.gw = gateway
        self.stage = stage
        self.tool_names = [t["name"] for t in defn.get("tools", []) if t["name"] in REGISTRY]
        self.toolbox = ToolBox(self.tool_names, tables or {}, offline=offline_tools, now=now, record=tool_record)
        self.system = D.render_system_prompt(defn) + "\n\n" + CONTRACT_FOOTER + \
            ("\n" + TOOL_FOOTER if self.tool_names else "")
        m = defn["model"]
        self._temp = float(m.get("temperature", 0.0))
        self._max_tokens = int(m.get("max_tokens", 700))

    # ------------------------------------------------------------------ load
    @classmethod
    def from_path(cls, path: Path, gateway: Gateway, **kw) -> "AgentRuntime":
        path = Path(path)
        defn = D.load(path)
        kdir = path.parent / defn["knowledge"]["index_dir"]
        index = KnowledgeIndex.load(kdir)
        tables = read_json(kdir / "tables.json") if (kdir / "tables.json").exists() else {}
        return cls(defn, index, gateway, tables, **kw)

    # ------------------------------------------------------------- retrieval
    def retrieve(self, question: str) -> list[Hit]:
        r = self.defn["knowledge"]["retrieval"]
        kw = dict(top_k=int(r.get("top_k", 6)), bm25_weight=float(r.get("bm25_weight", 0.4)),
                  gateway=self.gw, neighbours=int(r.get("neighbours", 0)))
        hits = self.index.search(question, **kw)
        if r.get("query_rewrite"):
            try:
                rq = self.gw.run_prompt("agent", "agent.query_rewrite", {"type": "object", "properties": {
                    "query": {"type": "string", "minLength": 2}}, "required": ["query"]},
                    stage=f"{self.stage}.rewrite", question=question,
                    domain=self.defn.get("description", ""))["query"]
                extra = self.index.search(rq, **kw)
                # interleave original and rewritten results, de-duplicated
                merged: list[Hit] = []
                seen: set[str] = set()
                primary = [h for h in hits if not h.neighbour]
                second = [h for h in extra if not h.neighbour]
                for a, b in zip(primary + [None] * len(second), second + [None] * len(primary)):
                    for h in (a, b):
                        if h is not None and h.chunk.chunk_id not in seen and len(merged) < kw["top_k"]:
                            merged.append(h)
                            seen.add(h.chunk.chunk_id)
                nbrs = [h for h in hits + extra if h.neighbour and h.chunk.chunk_id not in seen]
                hits = merged + nbrs[: max(0, len(nbrs))]
            except LLMError:
                pass
        return hits

    # ---------------------------------------------------------------- answer
    def answer(self, question: str, history: list[dict] | None = None) -> dict:
        t0 = time.time()
        res: dict = {"question": question, "answer": "", "citations": [], "cited_chunks": [], "cited_tools": [],
                     "refused": False, "retrieved": [], "tool_calls": [], "contexts": {}, "guard_events": [],
                     "error": None}
        query = question
        if history:
            last_q = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
            if last_q and len(question.split()) < 7:
                query = f"{last_q} {question}"
        try:
            hits = self.retrieve(query)
        except LLMError as e:
            res["error"] = f"retrieval: {e}"
            hits = []
        labels: dict[str, str] = {}
        ctx_lines = []
        for i, h in enumerate(hits, start=1):
            lab = f"C{i}"
            labels[lab] = h.chunk.chunk_id
            res["contexts"][lab] = h.chunk.text
            ctx_lines.append(f"[{lab}] {h.chunk.header}\n{h.chunk.text}")
            res["retrieved"].append({"label": lab, "chunk_id": h.chunk.chunk_id, "doc_id": h.chunk.doc_id,
                                     "dense": round(h.dense, 4), "lexical": round(h.lexical, 3),
                                     "neighbour": h.neighbour})
        guards = self.defn.get("guards", {})
        top_dense = max((h.dense for h in hits if not h.neighbour), default=0.0)
        res["top_relevance"] = round(top_dense, 4)
        thr = float(guards.get("min_relevance", 0.0) or 0.0)
        if thr > 0 and self.index.unit is not None and top_dense < thr and not self.tool_names:
            res.update(refused=True, answer=self.defn["refusal_policy"]["message"])
            res["guard_events"].append(f"relevance {top_dense:.3f} < threshold {thr:.3f}: abstained")
            res["latency_s"] = round(time.time() - t0, 2)
            return res

        sources = "\n\n".join(ctx_lines) if ctx_lines else "(no passages matched)"
        tools_txt = f"\n\nTOOLS YOU MAY CALL:\n{self.toolbox.describe()}" if self.tool_names else ""
        hist_txt = ""
        if history:
            turns = history[-4:]
            hist_txt = "CONVERSATION SO FAR:\n" + "\n".join(f"{h['role']}: {h['content'][:400]}" for h in turns) + "\n\n"
        user = f"{hist_txt}SOURCES (cite by label):\n{sources}{tools_txt}\n\nQUESTION: {question}"
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": user}]
        rounds = int(guards.get("max_tool_rounds", 2)) if self.tool_names else 0
        out: dict | None = None
        try:
            for rnd in range(rounds + 1):
                final = rnd == rounds or not self.tool_names
                schema = _answer_schema(None if final else self.tool_names)
                out = self.gw.chat_json("agent", messages, schema, stage=self.stage, prompt_id="agent.answer",
                                        temperature=self._temp, max_tokens=self._max_tokens)
                calls = [] if final else (out.get("tool_calls") or [])
                if not calls:
                    break
                tool_lines = []
                for c in calls[:2]:
                    name = c.get("tool", "")
                    r = self.toolbox.run(name, c.get("arguments") or {})
                    lab = f"T{len(res['tool_calls']) + 1}"
                    text = r.get("result") if r.get("ok") else f"ERROR: {r.get('error')}"
                    res["tool_calls"].append({"label": lab, "tool": name, "arguments": c.get("arguments") or {},
                                              "ok": bool(r.get("ok")), "result": text, "rows": r.get("rows", [])})
                    res["contexts"][lab] = text
                    tool_lines.append(f"[{lab}] {name}({c.get('arguments')}) ->\n{text}")
                messages = messages + [
                    {"role": "assistant", "content": '{"tool_calls": ' + str(calls)[:1500] + "}"},
                    {"role": "user", "content": "TOOL RESULTS (cite by label):\n" + "\n\n".join(tool_lines) +
                     "\n\nNow answer the QUESTION. Use further tools only if essential."},
                ]
        except LLMError as e:
            res["error"] = f"model: {e}"
            out = None
        if out is None:
            res.update(refused=True, answer="Sorry - I could not produce a reliable answer to that just now.")
            res["guard_events"].append("model output unavailable: safe refusal")
            res["latency_s"] = round(time.time() - t0, 2)
            return res

        answer = str(out.get("answer", "")).strip()
        refused = bool(out.get("refused", False))
        cites = []
        for c in out.get("citations") or []:
            c = str(c).strip().strip("[]")
            if c in res["contexts"] and c not in cites:
                cites.append(c)
            elif c:
                res["guard_events"].append(f"dropped invalid citation {c!r}")
        if not refused and not answer:
            refused = True
            answer = self.defn["refusal_policy"]["message"]
            res["guard_events"].append("empty answer treated as refusal")
        if refused and not answer:
            answer = self.defn["refusal_policy"]["message"]
        if not refused and not cites and looks_like_refusal(answer) and len(answer) < 300:
            refused = True
            res["guard_events"].append("answer reads as a refusal: refused flag set")
        res.update(answer=answer, refused=refused, citations=cites,
                   cited_chunks=[labels[c] for c in cites if c in labels],
                   cited_tools=[c for c in cites if c.startswith("T")])
        for tc in res["tool_calls"]:
            if tc["label"] in cites:
                res["cited_chunks"].extend(r for r in tc.get("rows", []) if r not in res["cited_chunks"])
        res["latency_s"] = round(time.time() - t0, 2)
        return res
