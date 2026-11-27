"""Stage 5 - Judge: deterministic first, model second, and the model is audited.

Per case it decides: refused when it should? correct against the expected
key facts? grounded (every claim supported by what the agent actually saw)?
cited? used the expected tool?

Defences against the known LLM-as-judge failure modes
  position bias    - no pairwise comparisons at all: every judgement is
                     pointwise (one fact vs one answer; one claim vs sources).
                     The prompt tournament also ranks candidates by pointwise
                     pass rates, never by asking "which is better, A or B".
  verbosity bias   - binary per-fact questions instead of holistic scores; the
                     judge must return the exact words that state the fact and
                     the quote is verified; a padded-answer canary measures any
                     residual length effect every run.
  self-preference  - the judge model is from a different family than the agent
                     (checked and reported), and most verdicts never reach a
                     model: exact/numeric fact matching, refusal flags from the
                     output contract, citation validity and numeric
                     faithfulness are pure code.
  judge drift      - every run scores labelled canaries (gold, corrupted,
                     padded, fabricated-claim answers) and reports the judge's
                     own accuracy next to the agent's score.
"""

from __future__ import annotations

import re

from forgeai.llm.gateway import Gateway, LLMError
from forgeai.llm.schema import BOOL, STR, arr, obj
from forgeai.util.text import (content_tokens, fact_match, looks_like_refusal, normalize, numbers_in, quote_in,
                               split_sentences)

FACT_SCHEMA = obj({"stated": BOOL, "quote": STR})
CLAIMS_SCHEMA = obj({"verdicts": arr(obj({"id": STR, "supported": BOOL, "quote": STR}), 0, 20)})

CATEGORIES = {
    "retrieval_miss": "the passage with the answer was never retrieved, so the model could not see it",
    "prompt_defect": "the right passage was retrieved but the agent's behaviour was wrong (incomplete, uncited, "
                     "answered something it should refuse, or did not use its tool)",
    "hallucination": "the answer states things that are not in any source the agent saw",
    "wrong_refusal": "the agent refused although the answer was in the retrieved passages",
}

_FILLER = re.compile(r"^(?:let me know|feel free|i hope|hope this|please (?:let|feel|contact|reach)|"
                     r"if you (?:have|need)|is there anything|thank|you(?:'re| are) welcome|"
                     r"(?:here is|here's) (?:the|a) )", re.I)


def _is_filler(sent: str) -> bool:
    return len(content_tokens(sent)) < 3 or bool(_FILLER.match(sent.strip())) or looks_like_refusal(sent)


class Judge:
    def __init__(self, gw: Gateway, stage: str = "judge"):
        self.gw = gw
        self.stage = stage

    # ----------------------------------------------------------------- facts
    def fact_stated(self, fact: str, answer: str) -> dict:
        verdict, score = fact_match(fact, answer)
        if verdict == "match":
            return {"text": fact, "stated": True, "method": "deterministic", "quote": ""}
        if verdict == "miss":
            return {"text": fact, "stated": False, "method": "deterministic", "quote": ""}
        try:
            v = self.gw.run_prompt("judge", "judge.fact", FACT_SCHEMA, stage=f"{self.stage}.fact", fact=fact,
                                   answer=answer[:2500])
        except LLMError:
            return {"text": fact, "stated": False, "method": "judge-error", "quote": ""}
        quote = v.get("quote", "")
        nums_ok = numbers_in(fact).issubset(numbers_in(answer))
        verified = bool(quote) and quote_in(quote, answer)
        if v["stated"] and verified and nums_ok:
            stated, method = True, "llm+quote-verified"
        elif v["stated"] and nums_ok and score >= 0.5:
            stated, method = True, "llm+lexical-support (quote not verbatim)"
        elif v["stated"] and nums_ok and _anchors(fact) and all(a in normalize(answer) for a in _anchors(fact)):
            stated, method = True, "llm+anchors-present (quote not verbatim)"
        elif v["stated"]:
            stated, method = False, "llm said yes but evidence failed verification"
        else:
            stated, method = False, "llm"
        return {"text": fact, "stated": stated, "method": method, "quote": quote if stated else "",
                "llm_said": bool(v["stated"])}

    # ---------------------------------------------------------------- claims
    def claims(self, answer: str, contexts: dict[str, str], question: str) -> list[dict]:
        """Faithfulness: every non-filler sentence must be supported by what the agent saw."""
        answer = re.sub(r"\s*\[(?:[CT]\d+(?:,\s*)?)+\]", "", answer or "")      # citation markers are not claims
        sents = []
        for sent in split_sentences(answer):
            sents.extend(p.strip() for p in re.split(r";\s+", sent) if p.strip())
        sents = [s for s in sents if not _is_filler(s)]
        if not sents:
            return []
        src_text = "\n".join(contexts.values())
        src_nums = numbers_in(src_text) | numbers_in(question)
        src_toks = [set(content_tokens(t)) for t in contexts.values()]
        union = set().union(*src_toks) if src_toks else set()
        out, pending = [], []
        for i, s in enumerate(sents):
            nums = numbers_in(s)
            stoks = set(content_tokens(s))
            bad_nums = sorted(n for n in nums if n not in src_nums and not _derivable(n, src_nums))
            best = max((len(stoks & t) / max(1, len(stoks)) for t in src_toks), default=0.0)
            # a sentence that combines several sources (or a tool result and a table row) is
            # supported by their union: credit it slightly below single-source support
            best = max(best, 0.95 * len(stoks & union) / max(1, len(stoks)))
            rec = {"id": f"S{i + 1}", "claim": s, "supported": None, "method": "", "quote": "", "overlap": round(best, 2)}
            if bad_nums:
                rec.update(supported=False, method=f"deterministic: numbers {bad_nums} appear in no source")
            elif best >= 0.75:
                rec.update(supported=True, method="deterministic: lexical support")
            else:
                pending.append(rec)
            out.append(rec)
        if pending:
            sources = "\n\n".join(f"[{k}] {v[:1200]}" for k, v in contexts.items()) or "(none)"
            claims = "\n".join(f"{r['id']}: {r['claim']}" for r in pending)
            try:
                vs = self.gw.run_prompt("judge", "judge.claims", CLAIMS_SCHEMA, stage=f"{self.stage}.claims",
                                        sources=sources[:9000], claims=claims)["verdicts"]
            except LLMError:
                vs = []
            by_id = {v["id"]: v for v in vs}
            for r in pending:
                v = by_id.get(r["id"])
                if v is None:
                    r.update(supported=r["overlap"] >= 0.5, method="judge-missing: lexical fallback")
                    continue
                q = v.get("quote", "")
                verified = bool(q) and quote_in(q, src_text)
                if v["supported"] and (verified or r["overlap"] >= 0.5):
                    r.update(supported=True, method="llm+evidence", quote=q if verified else "")
                elif v["supported"]:
                    r.update(supported=False, method="llm said supported but gave no verifiable evidence")
                else:
                    r.update(supported=False, method="llm")
        return out

    # ------------------------------------------------------------------ case
    def judge(self, case: dict, resp: dict) -> dict:
        exp = case["expected"]
        refused = bool(resp.get("refused"))
        retrieved = {r["chunk_id"] for r in resp.get("retrieved", [])}
        for tc in resp.get("tool_calls", []):
            retrieved.update(tc.get("rows", []))
        v: dict = {"id": case["id"], "kind": case["kind"], "split": case["split"], "should_refuse": exp["should_refuse"],
                   "refused": refused, "facts": [], "fact_recall": None, "claims": [], "grounded": None,
                   "cited": bool(resp.get("citations")), "gold_retrieved": None, "tool_ok": None,
                   "pass": False, "failure": None}
        if resp.get("error"):
            v["runtime_error"] = resp["error"]

        if exp["should_refuse"]:
            v["pass"] = refused
            if not refused:
                v["claims"] = self.claims(resp.get("answer", ""), resp.get("contexts", {}), case["question"])
                unsup = [c for c in v["claims"] if not c["supported"]]
                v["grounded"] = not unsup
                v["failure"] = ({"category": "hallucination", "subtype": "answered_out_of_scope",
                                 "detail": f"should refuse; answered with {len(unsup)} unsupported claim(s)"}
                                if unsup else
                                {"category": "prompt_defect", "subtype": "missed_refusal",
                                 "detail": "should refuse (out of scope) but answered from loosely related passages"})
            return v

        # Retrieval attribution is chunking-independent: a key fact counts as
        # retrieved when its verbatim text is inside something the agent saw.
        seen_texts = list(resp.get("contexts", {}).values())
        facts = exp.get("key_facts", [])
        fact_seen = [any(fact_match(f["text"], t)[0] == "match" for t in seen_texts) for f in facts]
        v["gold_retrieved"] = all(fact_seen) if facts else None
        v["facts_retrieved"] = sum(fact_seen)
        expected_tool = exp.get("tool")
        if expected_tool:
            v["tool_ok"] = any(t["tool"] == expected_tool and t["ok"] for t in resp.get("tool_calls", []))
        if refused:
            miss = bool(facts) and not all(fact_seen)
            v["failure"] = {"category": "retrieval_miss" if miss else "wrong_refusal",
                            "subtype": "refused_no_evidence" if miss else "refused_with_evidence",
                            "detail": "refused; gold passage " + ("not retrieved" if miss else "WAS retrieved")}
            if expected_tool and not v["tool_ok"]:
                v["failure"] = {"category": "prompt_defect", "subtype": "tool_not_used",
                                "detail": f"refused instead of calling {expected_tool}"}
            return v

        answer = resp.get("answer", "")
        v["facts"] = [self.fact_stated(f["text"], answer) for f in facts]
        n_ok = sum(1 for f in v["facts"] if f["stated"])
        v["fact_recall"] = (n_ok / len(facts)) if facts else None
        correct = (n_ok >= max(1, -(-2 * len(facts) // 3))) if facts else True
        if expected_tool in ("weather", "current_date"):
            correct = bool(v["tool_ok"])
        v["claims"] = self.claims(answer, resp.get("contexts", {}), case["question"])
        unsup = [c for c in v["claims"] if not c["supported"]]
        v["grounded"] = not unsup
        trap = exp.get("trap")
        if trap and not correct and fact_match(trap, answer)[0] == "match":
            v["trap_taken"] = True
        v["pass"] = correct and v["grounded"] and v["cited"] and (v["tool_ok"] is not False)

        if not v["pass"]:
            missing = [f for f, r in zip(facts, v["facts"]) if not r["stated"]]
            missing_not_retrieved = [f for f, r, s in zip(facts, v["facts"], fact_seen) if not r["stated"] and not s]
            if expected_tool and not v["tool_ok"]:
                v["failure"] = {"category": "prompt_defect", "subtype": "tool_not_used",
                                "detail": f"expected a {expected_tool} call"}
            elif v.get("trap_taken") and not missing_not_retrieved:
                v["failure"] = {"category": "prompt_defect", "subtype": "rule_misapplied",
                                "detail": f"applied the wrong condition: gave '{trap}' instead of '{missing[0]['text']}'"}
            elif missing_not_retrieved and not correct:
                v["failure"] = {"category": "retrieval_miss", "subtype": "fact_passage_not_retrieved",
                                "detail": f"{len(missing_not_retrieved)} missing fact(s) were in passages never retrieved"}
            elif unsup:
                v["failure"] = {"category": "hallucination", "subtype": "unsupported_claims",
                                "detail": "; ".join(c["claim"][:120] for c in unsup[:2])}
            elif not correct:
                v["failure"] = {"category": "prompt_defect", "subtype": "incomplete_or_wrong",
                                "detail": "evidence retrieved but key fact(s) missing: " +
                                          "; ".join(f["text"] for f in missing[:3])}
            else:
                v["failure"] = {"category": "prompt_defect", "subtype": "no_citation",
                                "detail": "answer correct but cites no source"}
        return v


def _anchors(fact: str) -> set[str]:
    """Distinctive tokens of a fact: numbers, acronyms and mid-sentence proper names
    (e.g. HRBP, KestrelHR, 30). If the model says a fact is stated, every anchor must
    actually be in the answer."""
    import re as _re
    words = _re.findall(r"[A-Za-z][\w-]*|\d[\d,.]*", fact)
    keep = [w for i, w in enumerate(words) if any(ch.isdigit() for ch in w) or (len(w) >= 2 and w.isupper())
            or (i > 0 and w[:1].isupper() and w.lower() not in ("i",))]
    return set(content_tokens(" ".join(keep)))


def _derivable(n: str, src: set[str]) -> bool:
    """Numbers that are trivially derived (sums/products/differences of two
    source numbers, or percentages) are not treated as fabricated."""
    try:
        x = float(n)
    except ValueError:
        return False
    vals = []
    for s in list(src)[:60]:
        try:
            vals.append(float(s))
        except ValueError:
            pass
    if x in (0, 1, 2, 100):
        return True
    for i, a in enumerate(vals):
        for b in vals[i:]:
            for r in (a + b, a * b, abs(a - b), a / b if b else None, b / a if a else None):
                if r is not None and abs(r - x) < 1e-6 * max(1.0, abs(x)) + 0.01:
                    return True
    return False


# -------------------------------------------------------------- canaries
FABRICATIONS = [
    "In addition, a one-time bonus of 7,345 is paid automatically.",
    "This was introduced by the regional director in 1987.",
    "Approval is always granted within 3 minutes.",
]


def _corrupt(fact: str, substitute: str) -> str:
    """Numeric facts get wrong numbers; non-numeric facts are swapped for a
    fact from a different case (wording that is plausible but wrong)."""
    def bump(m: re.Match) -> str:
        s = m.group(0)
        try:
            v = float(s.replace(",", ""))
            return str(int(v * 3 + 7)) if v.is_integer() else f"{v * 3 + 0.7:.2f}"
        except ValueError:
            return s
    out = re.sub(r"\d[\d,]*(?:\.\d+)?", bump, fact)
    return out if out != fact else substitute


def canaries(judge: Judge, cases: list[dict], max_cases: int = 6) -> dict:
    """Score the judge itself on answers whose correct verdict is known."""
    base = [c for c in cases if c["kind"] in ("answerable", "multi_doc") and c["expected"]["key_facts"]][:max_cases]
    results = {"gold_pass": [], "corrupted_fail": [], "padded_pass": [], "fabrication_caught": []}
    padding = (" To give you the complete picture, it is worth explaining the background in some detail. "
               "Policies like this exist to make processes fair, consistent and transparent for everyone involved, "
               "and they are reviewed regularly. Always keep your records organised.")
    for i, c in enumerate(base):
        facts = [f["text"] for f in c["expected"]["key_facts"]]
        gold = "According to the sources: " + "; ".join(facts) + "."
        ctx = {"C1": gold}
        other = base[(i + 1) % len(base)]["expected"]["key_facts"] if len(base) > 1 else []
        subst = "; ".join(f["text"] for f in other) or "no such provision exists"
        if any(fact_match(f, subst)[0] != "miss" for f in facts):
            subst = "no such provision exists"
        corrupted = "According to the sources: " + "; ".join(_corrupt(f, subst) for f in facts) + "."
        r_gold = [judge.fact_stated(f, gold)["stated"] for f in facts]
        r_cor = [judge.fact_stated(f, corrupted)["stated"] for f in facts]
        r_pad = [judge.fact_stated(f, gold + padding)["stated"] for f in facts]
        results["gold_pass"].append(all(r_gold))
        results["corrupted_fail"].append(not any(r_cor))
        results["padded_pass"].append(all(r_pad))
        fab = gold + " " + FABRICATIONS[i % len(FABRICATIONS)]
        cl = judge.claims(fab, ctx, c["question"])
        results["fabrication_caught"].append(any(not x["supported"] for x in cl))
    summary = {k: (sum(v) / len(v) if v else None) for k, v in results.items()}
    flat = [x for v in results.values() for x in v]
    summary["overall"] = sum(flat) / len(flat) if flat else None
    summary["n_canaries"] = len(flat)
    if summary["gold_pass"] is not None and summary["padded_pass"] is not None:
        summary["verbosity_effect"] = round(summary["padded_pass"] - summary["gold_pass"], 3)
    return summary
