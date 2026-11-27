"""Stage 4 - Eval generator (generated, never hand-written; prompts committed).

Case kinds
  answerable   one passage -> question + key facts
  multi_doc    two passages from DIFFERENT documents -> needs both
  edge         answerable case re-phrased (vague / typo / situational)
  tool         needs an attached tool (lookup / arithmetic / date / weather)
  out_of_scope near-miss question absent from the documents  -> must refuse
  must_refuse  policy refusal topic from the requirements     -> must refuse
  gap          probe of a groundability gap                    -> must refuse

The generator distrusts itself. Every case passes deterministic checks:
  * key facts must occur VERBATIM in the source passage (repaired to the exact
    span when the model paraphrased; dropped when they do not exist)
  * a question may not give away its own answer
  * closed-book leakage probe: if the agent's model answers correctly WITHOUT
    documents, the case measures memory, not grounding -> dropped
  * out-of-scope labels are verified: if the corpus actually answers the
    "refuse" question, the case is dropped (mislabelled test)
  * near-duplicates removed; arithmetic cases are re-computed by the calculator
  * dev/holdout split is stratified by kind and grouped by origin, so a
    re-phrased case never leaks across the split
Drop counts per reason are reported as eval-set quality evidence.
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict

from forgeai.factory.context import Run
from forgeai.llm.gateway import LLMError
from forgeai.llm.schema import BOOL, NESTR, STR, arr, obj
from forgeai.runtime.tools import REGISTRY, safe_eval
from forgeai.util import console as C
from forgeai.util.io import write_json
from forgeai.util.text import best_span, fact_match, jaccard, normalize, numbers_in

ANS_SCHEMA = obj({"question": NESTR, "answer": NESTR, "answer_span": NESTR})
_VAGUE = re.compile(r"\b(?:this|the|that) (?:policy|document|passage|section|text|guide|procedure|standard)\b|"
                    r"\bpurpose of\b|\bscope of\b|\bintroduction\b|\boverview of\b|"
                    r"\bmain (?:focus|aim|purpose|objective|goal|idea)\b|\bwhat (?:is|are) .{0,40}\babout\b|"
                    r"\bwhat (?:does|do) .{0,40}\b(?:cover|outline|describe)\b", re.I)
_QUANTITY_Q = re.compile(r"\b(?:how (?:many|much|long|soon|often|far)|deadline|limit|maximum|minimum|max|min|cost|"
                         r"price|rate|amount|percentage|within|by when|what time|how old)\b", re.I)
GENERIC = frozenset(("adhere provision provisions policy policies guideline guidelines ensure ensures comply "
                    "compliance staff employee employees must strictly procedure procedures standard standards applicable "
                    "relevant company process processes accordance requirement requirements outline outlined establish "
                    "establishes operational ethical all shore business related plan planning undertake undertaking "
                    "follow following apply applies section rules rule general purpose aim aims overall maintain "
                    "appropriate expected manner").split())


def _informative(fact: str, question: str, passage: str) -> str | None:
    """Reject facts a correct answer would not need to state: boilerplate, or a
    quantity question whose 'fact' omits the quantity."""
    from forgeai.util.text import content_tokens as ct
    toks = ct(fact)
    has_num = bool(numbers_in(fact))
    generic = {t for t in ct(" ".join(GENERIC))}
    if not has_num and toks and sum(1 for t in toks if t in generic) / len(toks) >= 0.6:
        return "boilerplate fact"
    if _QUANTITY_Q.search(question) and numbers_in(passage) and not has_num:
        return "quantity question but the fact holds no number"
    return None


def _vague(q: str) -> bool:
    """Questions that only make sense next to the source ('what is the purpose of this policy?')."""
    return bool(_VAGUE.search(q)) or len(q.split()) < 4
MULTI_SCHEMA = obj({"question": NESTR, "answer": NESTR, "fact_a": NESTR, "fact_b": NESTR})
REPHRASE_SCHEMA = obj({"question": NESTR})
OOS_SCHEMA = obj({"questions": arr(obj({"question": NESTR, "why_refuse": STR}), 1, 10)})
VERIFY_SCHEMA = obj({"answerable": BOOL, "quote": STR})
TOOL_SCHEMA = obj({"question": NESTR, "answer": NESTR, "key_facts": arr(NESTR, 1, 2)})
CALC_SCHEMA = obj({"question": NESTR, "expression": NESTR, "answer": NESTR})
APP_SCHEMA = obj({"applicable": BOOL, "question": STR, "answer_span": STR, "trap_span": STR, "condition": STR})
_CONDITIONAL = re.compile(r"\b(?:if|when|above|below|over|under|more than|less than|up to|exceed\w*|other|otherwise|"
                          r"except|only|metro|domestic|international|during|after|before|per)\b", re.I)

REPHRASE_MODES = [
    "short, vague question typed in a hurry: lower case, no punctuation, one small typo",
    "question that describes the user's own situation instead of naming the topic directly",
]


def plan_counts(target: int, n_docs: int, tools: list[str], n_gaps: int) -> dict:
    tool_n = min(len(tools), 3)
    refuse_n = max(5, round(target * 0.2))
    gap_n = min(n_gaps, 2)
    multi_n = 4 if n_docs >= 2 else 2
    edge_n = 4
    app_n = 4
    ans_n = max(8, target - tool_n - refuse_n - gap_n - multi_n - edge_n - app_n)
    return {"answerable": ans_n, "multi_doc": multi_n, "edge": edge_n, "application": app_n, "tool": tool_n,
            "refuse": refuse_n, "gap": gap_n}


def _verify_facts(facts: list[str], passage: str, question: str) -> tuple[list[str], list[str]]:
    """Verbatim (or repaired-to-verbatim) facts that are informative for the question."""
    kept, notes = [], []
    for f in facts:
        f = f.strip().strip(".")
        if not f:
            continue
        if normalize(f) in normalize(passage):
            span = f
        else:
            span = best_span(f, passage)
            if span is None:
                notes.append(f"fact not in source: {f!r}")
                continue
            notes.append(f"fact repaired to verbatim span: {f!r} -> {span!r}")
        if fact_match(span, question)[0] == "match" and len(span.split()) > 1:
            notes.append(f"fact given away by question: {span!r}")
            continue
        why = _informative(span, question, passage)
        if why:
            notes.append(f"{why}: {span!r}")
            continue
        if span not in kept:
            kept.append(span)
    return kept, notes


def _sample_chunks(run: Run, n: int, rng: random.Random) -> list:
    """Topic-first then stratified-by-document sampling of substantive chunks."""
    assert run.index is not None
    good = [c for c in run.chunks if len(c.text) >= 160 or (c.kind == "row" and len(c.text) >= 40)]
    chosen, seen = [], set()
    for t in run.groundability.get("topics", []):
        if t["verdict"] in ("supported", "partial") and t["evidence"]:
            cid = t["evidence"][0]["chunk_id"]
            c = run.index.by_id.get(cid)
            if c and cid not in seen:
                chosen.append(c)
                seen.add(cid)
    by_doc = defaultdict(list)
    for c in good:
        if c.chunk_id not in seen:
            by_doc[c.doc_id].append(c)
    for v in by_doc.values():
        rng.shuffle(v)
    docs = sorted(by_doc, key=lambda d: (-len(by_doc[d]), d))
    # text documents get more weight than table rows
    while len(chosen) < n and any(by_doc.values()):
        for d in docs:
            if by_doc[d] and len(chosen) < n:
                c = by_doc[d].pop()
                if c.kind == "row" and sum(1 for x in chosen if x.kind == "row") >= max(2, n // 4):
                    continue
                chosen.append(c)
    return chosen[:n]


def generate(run: Run, agent_defn: dict) -> dict:
    s = run.settings
    rng = random.Random(s.seed)
    req, g = run.requirements, run.groundability
    tools = [t["name"] for t in agent_defn.get("tools", [])]
    counts = plan_counts(s.eval_target, len(run.docs), tools, len(g.get("gaps", [])))
    audience = req.get("audience", "users")
    stats: Counter = Counter()
    notes: list[str] = []
    cases: list[dict] = []

    # ---------------------------------------------------------- answerable
    seeds = _sample_chunks(run, int(counts["answerable"] * 1.6) + 2, rng)

    def make_answerable(c):
        try:
            out = run.gw.run_prompt("factory", "evalgen.answerable", ANS_SCHEMA, stage="evalgen.answerable",
                                    audience=audience, source=c.doc_path, passage=c.text[:1800])
        except LLMError:
            return None, ["generation failed"]
        if _vague(out["question"]):
            return None, [f"vague question dropped: {out['question']!r}"]
        if len(out["answer_span"].split()) > 25:
            return None, [f"answer span too long to be a checkable fact: {out['answer_span'][:60]!r}"]
        facts, n = _verify_facts([out["answer_span"]], c.text, out["question"])
        return ({"kind": "answerable", "question": out["question"].strip(), "reference_answer": out["answer"],
                 "expected": {"should_refuse": False, "key_facts": [{"text": f, "chunk_id": c.chunk_id,
                                                                     "doc_id": c.doc_id} for f in facts],
                              "gold_chunks": [c.chunk_id], "source_docs": [c.doc_id]},
                 "provenance": {"prompt": "evalgen.answerable", "seed_chunk": c.chunk_id}} if facts else None), n

    for case, n in run.pmap(make_answerable, seeds, "generating answerable cases"):
        notes.extend(n)
        stats["answerable_generated"] += 1
        if case is None:
            stats["dropped_vague_question" if any("vague" in x for x in n) else "dropped_unverifiable_facts"] += 1
        else:
            cases.append(case)

    # ----------------------------------------------------------- multi-doc
    pairs = []
    text_chunks = [c for c in run.chunks if c.kind == "text" and len(c.text) > 150] or \
        [c for c in run.chunks if len(c.text) > 60]
    rng.shuffle(text_chunks)
    multi_doc_corpus = len({c.doc_id for c in run.chunks}) >= 2
    for a in text_chunks:
        if len(pairs) >= counts["multi_doc"] * 2:
            break
        hits = run.index.search(a.text[:600], top_k=12, bm25_weight=0.5, gateway=run.gw)
        for h in hits:
            b = h.chunk
            if b.chunk_id == a.chunk_id:
                continue
            if multi_doc_corpus and b.doc_id == a.doc_id:
                continue
            if not multi_doc_corpus and abs(int(re.sub(r"\D", "", b.chunk_id.split("#")[1]) or 0) -
                                            int(re.sub(r"\D", "", a.chunk_id.split("#")[1]) or 0)) < 2:
                continue
            pairs.append((a, b))
            break

    def make_multi(pair):
        a, b = pair
        try:
            out = run.gw.run_prompt("factory", "evalgen.multidoc", MULTI_SCHEMA, stage="evalgen.multidoc",
                                    audience=audience, source_a=a.doc_path, passage_a=a.text[:1400],
                                    source_b=b.doc_path, passage_b=b.text[:1400])
        except LLMError:
            return None, ["generation failed"]
        if _vague(out["question"]):
            return None, [f"vague question dropped: {out['question']!r}"]
        fa, na = _verify_facts([out["fact_a"]], a.text, out["question"])
        fb, nb = _verify_facts([out["fact_b"]], b.text, out["question"])
        if not fa or not fb:
            return None, na + nb
        return {"kind": "multi_doc", "question": out["question"].strip(), "reference_answer": out["answer"],
                "expected": {"should_refuse": False,
                             "key_facts": [{"text": fa[0], "chunk_id": a.chunk_id, "doc_id": a.doc_id},
                                           {"text": fb[0], "chunk_id": b.chunk_id, "doc_id": b.doc_id}],
                             "gold_chunks": [a.chunk_id, b.chunk_id], "source_docs": sorted({a.doc_id, b.doc_id})},
                "provenance": {"prompt": "evalgen.multidoc", "seed_chunks": [a.chunk_id, b.chunk_id]}}, na + nb

    for case, n in run.pmap(make_multi, pairs, "generating multi-document cases"):
        notes.extend(n)
        stats["multi_generated"] += 1
        if case is None:
            stats["dropped_unverifiable_facts"] += 1
        else:
            cases.append(case)

    # ------------------------------------------------- rule application
    # A concrete situation where a condition in the passage decides which value applies - the class of
    # question small models get wrong most often (quoting the right table, wrong row).
    app_pool = [c for c in run.chunks if c.kind == "text" and len(numbers_in(c.text)) >= 2 and _CONDITIONAL.search(c.text)]
    rng.shuffle(app_pool)

    def make_application(c):
        try:
            out = run.gw.run_prompt("factory", "evalgen.application", APP_SCHEMA, stage="evalgen.application",
                                    audience=audience, source=c.doc_path, passage=c.text[:1800])
        except LLMError:
            return None, ["generation failed"]
        if not out["applicable"] or not out["question"].strip() or _vague(out["question"]):
            return None, ["no conditional rule"]
        ans, n1 = _verify_facts([out["answer_span"]], c.text, out["question"])
        trap = out["trap_span"].strip().strip(".")
        trap = trap if normalize(trap) in normalize(c.text) else best_span(trap, c.text)
        if not ans or not trap or normalize(trap) == normalize(ans[0]) or numbers_in(trap) == numbers_in(ans[0]) \
                or fact_match(trap, ans[0])[0] == "match":
            return None, n1 + ["trap value missing or identical"]
        return {"kind": "application", "question": out["question"].strip(), "reference_answer": out["condition"],
                "expected": {"should_refuse": False, "key_facts": [{"text": ans[0], "chunk_id": c.chunk_id, "doc_id": c.doc_id}],
                             "trap": trap, "gold_chunks": [c.chunk_id], "source_docs": [c.doc_id]},
                "provenance": {"prompt": "evalgen.application", "seed_chunk": c.chunk_id, "condition": out["condition"]}}, n1

    for case, n in run.pmap(make_application, app_pool[: counts["application"] * 3], "generating rule-application cases"):
        notes.extend(n)
        stats["application_generated"] += 1
        if case is None:
            stats["dropped_application_unverified"] += 1
        else:
            cases.append(case)

    # ---------------------------------------------------------- tool cases
    for tname in tools:
        case = _tool_case(run, tname, audience, rng)
        stats[f"tool_{tname}_generated"] += 1
        if case:
            cases.append(case)
        else:
            stats["dropped_tool_case"] += 1

    # ------------------------------------------------ leakage / dedupe pass
    def closed_book(case):
        try:
            ans = run.gw.run_prompt("agent", "evalgen.closed_book", None, stage="evalgen.leakage",
                                    question=case["question"], max_tokens=200)
        except LLMError:
            return False
        facts = case["expected"]["key_facts"]
        return bool(facts) and all(fact_match(f["text"], ans)[0] == "match" for f in facts)

    answerables = [c for c in cases if c["kind"] in ("answerable", "multi_doc", "application")]
    leaks = run.pmap(closed_book, answerables, "leakage probe (closed-book)")
    for c, leaked in zip(answerables, leaks):
        c["provenance"]["closed_book_correct"] = bool(leaked)
    kept = []
    for c in cases:
        if c["provenance"].get("closed_book_correct"):
            stats["dropped_parametric_leakage"] += 1
            continue
        if any(jaccard(c["question"], k["question"]) > 0.6 for k in kept):
            stats["dropped_duplicate"] += 1
            continue
        kept.append(c)
    cases = kept
    by_kind = defaultdict(list)
    for c in cases:
        by_kind[c["kind"]].append(c)
    cases = by_kind["answerable"][: counts["answerable"]] + by_kind["multi_doc"][: counts["multi_doc"]] + \
        by_kind["application"][: counts["application"]] + by_kind["tool"]

    # --------------------------------------------------------------- edge
    bases = [c for c in cases if c["kind"] == "answerable"][: counts["edge"]]

    def make_edge(arg):
        i, base = arg
        mode = REPHRASE_MODES[i % len(REPHRASE_MODES)]
        try:
            q = run.gw.run_prompt("factory", "evalgen.rephrase", REPHRASE_SCHEMA, stage="evalgen.edge",
                                  question=base["question"], mode=mode)["question"].strip()
        except LLMError:
            return None
        if jaccard(q, base["question"]) > 0.85 or len(q) < 6:
            return None
        return {"kind": "edge", "question": q, "reference_answer": base["reference_answer"],
                "expected": dict(base["expected"]),
                "provenance": {"prompt": "evalgen.rephrase", "mode": mode, "origin_question": base["question"]},
                "_origin": id(base)}

    for e in run.pmap(make_edge, list(enumerate(bases)), "generating edge cases"):
        if e:
            cases.append(e)
        else:
            stats["dropped_edge_rephrase"] += 1

    # ----------------------------------------------------- refusal cases
    covered = "; ".join(sorted({t for p in run.profiles.values() for t in p.get("topics", [])})[:30])
    gaps = [x["topic"] for x in g.get("gaps", [])]

    def gen_refusals(kind, n, must_refuse, gap_txt):
        try:
            out = run.gw.run_prompt("factory", "evalgen.out_of_scope", OOS_SCHEMA, stage=f"evalgen.{kind}",
                                    summary=req["summary"], covered=covered or "(see documents)",
                                    must_refuse=must_refuse, gaps=gap_txt, n=n)["questions"]
        except LLMError:
            return []
        return [{"kind": kind, "question": q["question"].strip(), "reference_answer": req["out_of_scope_message"],
                 "expected": {"should_refuse": True, "key_facts": [], "gold_chunks": [], "source_docs": [],
                              "refuse_reason": q.get("why_refuse", "")},
                 "provenance": {"prompt": "evalgen.out_of_scope"}} for q in out]

    policy = "; ".join(t["topic"] for t in req["must_refuse"])
    refusal_pool = gen_refusals("out_of_scope", counts["refuse"] + 3, policy, "; ".join(gaps) or "(none)")
    if gaps and counts["gap"]:
        gap_pool = gen_refusals("gap", counts["gap"] + 1, "(none)", "; ".join(gaps[: counts["gap"]]))
    else:
        gap_pool = []

    def verify_absent(case):
        hits = run.index.search(case["question"], top_k=4, bm25_weight=0.4, gateway=run.gw)
        passages = "\n\n".join(f"[{h.chunk.chunk_id}] {h.chunk.text[:700]}" for h in hits)
        try:
            pid = "evalgen.verify_gap" if case["kind"] == "gap" else "evalgen.verify_oos"
            # two model families must agree the topic is absent (judge family + factory family)
            vs = [run.gw.run_prompt(role, pid, VERIFY_SCHEMA, stage="evalgen.verify_refusal",
                                    question=case["question"], passages=passages or "(none)") for role in ("judge", "factory")]
        except LLMError:
            return True
        from forgeai.util.text import content_tokens, quote_in
        really = any(v["answerable"] and (not v.get("quote") or any(quote_in(v["quote"], h.chunk.text) for h in hits))
                     for v in vs)
        case["provenance"]["label_votes"] = ["present" if v["answerable"] else "absent" for v in vs]
        # deterministic second opinion: if one passage covers most of the question's content words,
        # the "must refuse" label is doubtful - drop it rather than keep a possibly wrong test
        qt = set(content_tokens(case["question"]))
        cover = max((len(qt & set(content_tokens(h.chunk.indexed_text))) / len(qt) for h in hits), default=0.0) if qt else 0.0
        case["provenance"]["max_lexical_cover"] = round(cover, 2)
        if case["kind"] == "gap":   # topic already proven unsupported by the groundability audit
            return not really
        return not really and cover < 0.5

    pool = refusal_pool + gap_pool
    verdicts = run.pmap(verify_absent, pool, "verifying refusal labels")
    policy_topics = [normalize(t["topic"]) for t in req["must_refuse"]]
    ref_kept = []
    for c, absent in zip(pool, verdicts):
        is_policy = any(pt and (pt in normalize(c["expected"].get("refuse_reason", "")) or pt in normalize(c["question"]))
                        for pt in policy_topics)
        if is_policy and c["kind"] == "out_of_scope":
            c["kind"] = "must_refuse"
        if not absent and not is_policy:
            stats["dropped_refusal_label_wrong"] += 1
            continue
        if any(jaccard(c["question"], k["question"]) > 0.6 for k in ref_kept + cases):
            stats["dropped_duplicate"] += 1
            continue
        ref_kept.append(c)
    gaps_kept = [c for c in ref_kept if c["kind"] == "gap"][: counts["gap"]]
    others = [c for c in ref_kept if c["kind"] != "gap"][: counts["refuse"]]
    cases += others + gaps_kept

    # --------------------------------------------------------------- split
    cases = _split(cases, s.holdout_frac, rng)
    for i, c in enumerate(cases, 1):
        c["id"] = f"E{i:02d}"
        c.pop("_origin", None)
        c.pop("_group", None)
    kinds = Counter(c["kind"] for c in cases)
    if len(cases) < 20:
        C.warn(f"only {len(cases)} verified cases (target {s.eval_target}); the corpus is small or the model "
               "struggled - the report states this")
    result = {
        "cases": cases,
        "stats": {"total": len(cases), "by_kind": dict(kinds),
                  "dev": sum(1 for c in cases if c["split"] == "dev"),
                  "holdout": sum(1 for c in cases if c["split"] == "holdout"),
                  "should_refuse": sum(1 for c in cases if c["expected"]["should_refuse"]),
                  "checks": dict(stats), "plan": counts},
        "verification_notes": notes[:200],
    }
    write_json(run.path("05_evalset.json"), result)
    return result


def _split(cases: list[dict], holdout_frac: float, rng: random.Random) -> list[dict]:
    """Stratified by kind; an edge case always lands in the same split as the
    case it was re-phrased from (grouped by origin), so no paraphrase leaks."""
    groups: dict[int, list[dict]] = defaultdict(list)
    for c in cases:
        groups[c.get("_origin") or id(c)].append(c)
    by_kind: dict[str, list[int]] = defaultdict(list)
    for key, members in groups.items():
        root = next((m for m in members if m["kind"] != "edge"), members[0])
        by_kind[root["kind"]].append(key)
    split_of: dict[int, str] = {}
    for kind in sorted(by_kind):
        keys = by_kind[kind]
        rng.shuffle(keys)
        n_hold = int(round(len(keys) * holdout_frac))
        if len(keys) >= 2 and n_hold == 0:
            n_hold = 1
        for i, k in enumerate(keys):
            split_of[k] = "holdout" if i < n_hold else "dev"
    for key, members in groups.items():
        for m in members:
            m["split"] = split_of[key]
    order = {id(c): i for i, c in enumerate(cases)}
    return sorted(cases, key=lambda c: order[id(c)])


def _tool_case(run: Run, tname: str, audience: str, rng: random.Random) -> dict | None:
    spec = REGISTRY[tname]
    if tname == "weather":
        return {"kind": "tool", "question": _weather_question(run), "reference_answer": "(live data)",
                "expected": {"should_refuse": False, "key_facts": [], "gold_chunks": [], "source_docs": [],
                             "tool": "weather"}, "provenance": {"prompt": "(template: live data cannot have fixed facts)"}}
    if tname == "current_date":
        return {"kind": "tool", "question": "What is today's date?", "reference_answer": "(today's date)",
                "expected": {"should_refuse": False, "key_facts": [], "gold_chunks": [], "source_docs": [],
                             "tool": "current_date"}, "provenance": {"prompt": "(template: date depends on run day)"}}
    if tname == "csv_lookup":
        rows = [c for c in run.chunks if c.kind == "row"]
        if not rows:
            return None
        c = rng.choice(rows)
        try:
            out = run.gw.run_prompt("factory", "evalgen.tool", TOOL_SCHEMA, stage="evalgen.tool", audience=audience,
                                    tool=tname, tool_desc=spec.description, data=c.text,
                                    hint="Ask about one specific value in this row, identifying the row by its name, code or number.")
        except LLMError:
            return None
        facts, _ = _verify_facts(out["key_facts"], c.text, out["question"])
        if not facts:
            return None
        return {"kind": "tool", "question": out["question"], "reference_answer": out["answer"],
                "expected": {"should_refuse": False, "key_facts": [{"text": f, "chunk_id": c.chunk_id, "doc_id": c.doc_id}
                                                                   for f in facts],
                             "gold_chunks": [c.chunk_id], "source_docs": [c.doc_id], "tool": "csv_lookup"},
                "provenance": {"prompt": "evalgen.tool", "seed_chunk": c.chunk_id}}
    if tname == "calculator":
        cands = [c for c in run.chunks if len(numbers_in(c.text)) >= 2 and len(c.text) > 80]
        if not cands:
            return None
        for _ in range(3):
            c = rng.choice(cands)
            try:
                out = run.gw.run_prompt("factory", "evalgen.tool", CALC_SCHEMA, stage="evalgen.tool",
                                        audience=audience, tool=tname, tool_desc=spec.description, data=c.text[:1500],
                                        hint="It must need arithmetic on numbers stated in the data (e.g. a total for a "
                                             "quantity, or a difference). Also return \"expression\": the arithmetic "
                                             "expression using only those numbers.")
                val = safe_eval(out["expression"])
            except (LLMError, ValueError, SyntaxError, ZeroDivisionError, TypeError):
                continue
            used = numbers_in(out["expression"])
            if not used or not used.issubset(numbers_in(c.text) | {"100", "1", "2", "12", "7", "30", "365"}):
                continue
            vtxt = (str(int(val)) if float(val).is_integer() else f"{val:.2f}").rstrip("0").rstrip(".") \
                if isinstance(val, float) else str(val)
            return {"kind": "tool", "question": out["question"], "reference_answer": out["answer"],
                    "expected": {"should_refuse": False, "key_facts": [{"text": vtxt, "chunk_id": c.chunk_id,
                                                                        "doc_id": c.doc_id, "computed": out["expression"]}],
                                 "gold_chunks": [c.chunk_id], "source_docs": [c.doc_id], "tool": "calculator"},
                    "provenance": {"prompt": "evalgen.tool", "seed_chunk": c.chunk_id,
                                   "verified_by": "calculator re-computation"}}
        return None
    return None


def _weather_question(run: Run) -> str:
    text = " ".join(c.text for c in run.chunks[:300])
    m = re.findall(r"\b(?:port of|at|in)\s+([A-Z][a-z]{3,}(?:\s[A-Z][a-z]+)?)", text)
    place = Counter(m).most_common(1)[0][0] if m else "Mumbai"
    return f"What is the weather forecast for {place} for the next two days?"
