"""Stage 6 - Critic-optimizer loop (max 3 iterations), plus the prompt tournament.

Loop:  evaluate -> classify every failure (retrieval miss / prompt defect /
hallucination / wrong refusal; classification is measured by the judge, not
guessed) -> propose TARGETED patches -> gate each patch on the dev cases it
targets plus a regression sample -> merge accepted patches -> full re-eval ->
keep or revert the iteration.

Targeted means: a patch changes one prompt section, or one group of retrieval
parameters, or one guard - never a full regeneration. Every patch is logged
with what changed, why, which case ids it addressed and before/after scores.

Overfitting control: the critic only sees DEV failures. Holdout cases are
scored each iteration for reporting but never influence a decision.
"""

from __future__ import annotations

import copy
import itertools
import time
from collections import defaultdict
from pathlib import Path

from forgeai.factory.context import Run
from forgeai.factory.evaluate import evaluate, retrieval_recall, runtime_for
from forgeai.factory.judge import CATEGORIES, Judge
from forgeai.llm.gateway import BudgetExceeded, LLMError
from forgeai.llm.schema import NESTR, obj
from forgeai.runtime import definition as D
from forgeai.util import console as C
from forgeai.util.io import append_jsonl, write_json
from forgeai.util.stats import paired_flips
from forgeai.util.text import truncate

PATCH_SCHEMA = obj({"diagnosis": NESTR, "new_text": NESTR, "change_summary": NESTR})

SECTION_FOR = {
    "hallucination/unsupported_claims": "grounding",
    "hallucination/answered_out_of_scope": "refusal",
    "prompt_defect/missed_refusal": "refusal",
    "prompt_defect/incomplete_or_wrong": "grounding",
    "prompt_defect/no_citation": "grounding",
    "prompt_defect/tool_not_used": "tools",
    "prompt_defect/rule_misapplied": "grounding",
    "wrong_refusal/refused_with_evidence": "refusal",
}
MAX_CONTEXT_CHARS = 12000


# --------------------------------------------------------------- tournament
def tournament(run: Run, candidates: list[dict], cases: list[dict]) -> tuple[dict, list[dict]]:
    """Pick the system prompt by DEV pass rate (pointwise scores; no pairwise
    judging, hence no position bias). Ties -> fact recall -> grounded -> shorter."""
    rows = []
    for i, cand in enumerate(candidates):
        style = cand["system_prompt"].get("style", f"c{i}")
        res = evaluate(run, cand, cases, f"tournament:{style}", run.path("06_tournament", style),
                       splits=("dev",), stage="tournament")
        sc = res["scorecard"]
        rows.append({"style": style, "dev": sc["dev"], "fact_recall": sc["metrics"]["fact_recall_mean"] or 0,
                     "grounded": sc["metrics"]["grounded_rate"] or 0,
                     "prompt_chars": len(D.render_system_prompt(cand)), "fingerprint": sc["agent_fingerprint"]})
        C.info(f"{style:<10} dev {sc['dev']['passed']}/{sc['dev']['n']}  fact recall {rows[-1]['fact_recall']:.2f}  "
               f"grounded {rows[-1]['grounded']:.2f}")
    best = max(range(len(rows)), key=lambda i: (rows[i]["dev"]["rate"] or 0, rows[i]["fact_recall"],
                                                rows[i]["grounded"], -rows[i]["prompt_chars"]))
    for i, r in enumerate(rows):
        r["winner"] = i == best
    write_json(run.path("06_tournament", "tournament.json"), rows)
    return candidates[best], rows


# ------------------------------------------------------------------ patches
def _failure_text(cases_by_id: dict, verdicts: list[dict], responses: dict, limit: int = 6) -> str:
    out = []
    for v in verdicts[:limit]:
        c = cases_by_id[v["id"]]
        r = responses.get(v["id"], {})
        if c["expected"]["should_refuse"]:
            exp = "must REFUSE (out of scope)"
        else:
            exp = "answer must include: " + "; ".join(f["text"] for f in c["expected"]["key_facts"]) \
                if c["expected"]["key_facts"] else f"must use the {c['expected'].get('tool')} tool"
        did = ("REFUSED: " if r.get("refused") else "ANSWERED: ") + truncate(r.get("answer", ""), 260)
        out.append(f"- Q: {c['question']}\n  expected: {exp}\n  agent: {did}\n  judge: {v['failure']['detail'][:200]}")
    return "\n".join(out)


def _critic_patch(run: Run, defn: dict, section_id: str, category: str, failures: list[dict],
                  cases_by_id: dict, responses: dict) -> dict | None:
    sec = D.section(defn, section_id)
    current = sec["text"] if sec else ""
    try:
        out = run.gw.run_prompt("factory", "critic.patch", PATCH_SCHEMA, stage="optimize.critic",
                                category=category, category_meaning=CATEGORIES[category], section_id=section_id,
                                section_text=current or "(empty)",
                                failures=_failure_text(cases_by_id, failures, responses))
    except LLMError:
        return None
    new = out["new_text"].strip()
    if not new or new == current.strip() or len(new) > max(2500, 3 * len(current)):
        return None
    # never let a patch smuggle facts into the prompt: numbers not already present are rejected
    from forgeai.util.text import numbers_in
    added_nums = numbers_in(new) - numbers_in(current) - numbers_in(defn["refusal_policy"]["message"])
    if added_nums:
        return None
    nd = copy.deepcopy(defn)
    D.set_section(nd, section_id, new)
    return {"target": f"section:{section_id}", "category": category, "defn": nd,
            "diagnosis": out["diagnosis"], "change_summary": out["change_summary"],
            "before": current, "after": new}


def _retrieval_patch(run: Run, defn: dict, dev_cases: list[dict]) -> dict | None:
    k = defn["knowledge"]
    base = retrieval_recall(run, k["chunking"], k["retrieval"], dev_cases)
    cur_chars = int(k["chunking"]["max_chars"])
    grid = []
    for mc, tk, w, nb in itertools.product(sorted({cur_chars, 600, 1200}), sorted({k["retrieval"]["top_k"], 6, 8, 10}),
                                           (0.25, 0.4, 0.55, 0.7), (0, 1)):
        if mc * tk * (1.5 if nb else 1) > MAX_CONTEXT_CHARS:
            continue
        ch = {"max_chars": mc, "overlap": min(150, mc // 6)}
        rt = {**k["retrieval"], "top_k": tk, "bm25_weight": w, "neighbours": nb}
        grid.append((ch, rt))
    scored = []
    for ch, rt in grid:
        r = retrieval_recall(run, ch, rt, dev_cases)
        scored.append((r, -(ch["max_chars"] * rt["top_k"]), ch, rt))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0]
    if best[0] < base + 0.02:
        return None
    nd = copy.deepcopy(defn)
    nd["knowledge"]["chunking"], nd["knowledge"]["retrieval"] = best[2], best[3]
    return {"target": "retrieval", "category": "retrieval_miss", "defn": nd,
            "diagnosis": f"dev key-fact retrieval recall {base:.0%} with current parameters",
            "change_summary": f"chunking {k['chunking']} -> {best[2]}; retrieval top_k/bm25_weight/neighbours "
                              f"{k['retrieval']['top_k']}/{k['retrieval']['bm25_weight']}/{k['retrieval'].get('neighbours', 0)}"
                              f" -> {best[3]['top_k']}/{best[3]['bm25_weight']}/{best[3]['neighbours']} "
                              f"(measured recall {base:.0%} -> {best[0]:.0%} over {len(grid)} configurations)",
            "before": {"chunking": k["chunking"], "retrieval": k["retrieval"]},
            "after": {"chunking": best[2], "retrieval": best[3]}, "recall_before": base, "recall_after": best[0]}


def _rewrite_patch(defn: dict) -> dict | None:
    if defn["knowledge"]["retrieval"].get("query_rewrite"):
        return None
    nd = copy.deepcopy(defn)
    nd["knowledge"]["retrieval"]["query_rewrite"] = True
    return {"target": "retrieval:query_rewrite", "category": "retrieval_miss", "defn": nd,
            "diagnosis": "vaguely phrased questions do not match document vocabulary",
            "change_summary": "enable query rewriting (question -> document-vocabulary search query, merged with "
                              "original results)", "before": False, "after": True}


def _threshold_patch(defn: dict, dev_verdicts: list[dict], responses: dict) -> dict | None:
    """Calibrate an abstention threshold on dev: the largest relevance cut that
    keeps every answerable dev case above it while catching missed refusals."""
    if defn.get("tools"):
        return None
    ans = [responses[v["id"]]["top_relevance"] for v in dev_verdicts if not v["should_refuse"]
           and v["id"] in responses]
    oos = [responses[v["id"]]["top_relevance"] for v in dev_verdicts if v["should_refuse"] and not v["refused"]
           and v["id"] in responses]
    if not ans or not oos or max(oos) <= 0:
        return None
    floor = min(ans)
    caught = [x for x in oos if x < floor]
    if not caught:
        return None
    thr = round(min(floor - 0.01, max(caught) + 0.5 * (floor - max(caught))), 4)
    if thr <= 0:
        return None
    nd = copy.deepcopy(defn)
    nd["guards"]["min_relevance"] = thr
    return {"target": "guard:min_relevance", "category": "prompt_defect", "defn": nd,
            "diagnosis": f"{len(oos)} out-of-scope dev question(s) answered; their best passage relevance "
                         f"({', '.join(f'{x:.3f}' for x in sorted(oos))}) is below every answerable dev question "
                         f"({floor:.3f})",
            "change_summary": f"abstain when best passage relevance < {thr} (calibrated on dev; catches "
                              f"{len(caught)} of {len(oos)} missed refusals, 0 answerable dev cases below it)",
            "before": defn["guards"].get("min_relevance", 0.0), "after": thr}


def _gate(run: Run, patch: dict, base_verdicts: dict, targets: list[str], dev_cases: list[dict],
          cases_by_id: dict) -> dict:
    """Evaluate a patch on the cases it targets + a regression sample of passing dev cases."""
    passing = [c for c in dev_cases if base_verdicts[c["id"]]["pass"]]
    target_kinds = {cases_by_id[t]["kind"] for t in targets}
    passing.sort(key=lambda c: (c["kind"] not in target_kinds, c["id"]))
    subset_ids = list(dict.fromkeys(targets + [c["id"] for c in passing[:8]]))
    subset = [cases_by_id[i] for i in subset_ids]
    rt = runtime_for(run, patch["defn"], stage="optimize.gate.agent")
    judge = Judge(run.gw, stage="optimize.gate.judge")
    after = dict(run.pmap(lambda c: (c["id"], judge.judge(c, rt.answer(c["question"]))["pass"]), subset))
    before = {i: base_verdicts[i]["pass"] for i in subset_ids}
    flips = paired_flips(before, after)
    accepted = flips["net"] >= 1 and len(flips["broke"]) <= len(flips["fixed"]) // 3
    return {"subset": subset_ids, "fixed": flips["fixed"], "broke": flips["broke"], "accepted": accepted}


def _merge(base: dict, patches: list[dict]) -> dict:
    nd = copy.deepcopy(base)
    for p in patches:
        t = p["target"]
        if t.startswith("section:"):
            sid = t.split(":", 1)[1]
            D.set_section(nd, sid, D.section(p["defn"], sid)["text"])
        elif t == "retrieval":
            nd["knowledge"]["chunking"] = p["defn"]["knowledge"]["chunking"]
            nd["knowledge"]["retrieval"] = {**p["defn"]["knowledge"]["retrieval"],
                                            "query_rewrite": nd["knowledge"]["retrieval"].get("query_rewrite", False)}
        elif t == "retrieval:query_rewrite":
            nd["knowledge"]["retrieval"]["query_rewrite"] = True
        elif t == "guard:min_relevance":
            nd["guards"]["min_relevance"] = p["defn"]["guards"]["min_relevance"]
    return nd


# --------------------------------------------------------------------- loop
def optimize(run: Run, defn: dict, cases: list[dict], first: dict) -> tuple[dict, list[dict], dict]:
    s = run.settings
    cases_by_id = {c["id"]: c for c in cases}
    dev_cases = [c for c in cases if c["split"] == "dev"]
    log_path = run.path("07_changes.jsonl")
    current, cur_eval = defn, first
    history = [{"iteration": 0, "label": "baseline", "scorecard": first["scorecard"], "patches": [],
                "decision": "baseline", "fingerprint": D.fingerprint(defn)}]
    for it in range(1, s.max_iterations + 1):
        t0, tok0 = time.time(), run.gw.meter.fresh_tokens
        verdicts = {v["id"]: v for v in cur_eval["verdicts"]}
        responses = {r["case_id"]: r for r in cur_eval["responses"]}
        dev_fail = [v for v in cur_eval["verdicts"] if v["split"] == "dev" and not v["pass"]]
        if not dev_fail:
            C.ok(f"iteration {it}: every dev case passes - stopping (holdout is reported, never tuned on)")
            break
        if run.gw.budget_left() < 0.15:
            C.warn(f"iteration {it}: budget nearly exhausted ({run.gw.budget_left():.0%} left) - stopping early")
            history.append({"iteration": it, "decision": "stopped: budget", "patches": []})
            break
        C.stage(f"7.{it}", f"Critic-optimizer iteration {it}/{s.max_iterations}: {len(dev_fail)} dev failure(s)")
        groups: dict[str, list[dict]] = defaultdict(list)
        for v in dev_fail:
            groups[v["failure"]["category"]].append(v)
        for cat, vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            C.info(f"{cat:<15} {len(vs)}  ({', '.join(v['id'] for v in vs)})")

        proposals: list[tuple[dict, list[str]]] = []
        if "retrieval_miss" in groups:
            ids = [v["id"] for v in groups["retrieval_miss"]]
            p = _retrieval_patch(run, current, dev_cases)
            if p:
                proposals.append((p, ids))
            elif any(cases_by_id[i]["kind"] == "edge" for i in ids):
                p = _rewrite_patch(current)
                if p:
                    proposals.append((p, ids))
        by_section: dict[str, list[dict]] = defaultdict(list)
        for cat, vs in groups.items():
            for v in vs:
                key = f"{cat}/{v['failure']['subtype']}"
                if key in SECTION_FOR:
                    by_section[SECTION_FOR[key]].append(v)
        if any(v["should_refuse"] for v in dev_fail):
            p = _threshold_patch(current, [v for v in cur_eval["verdicts"] if v["split"] == "dev"], responses)
            if p:   # targets: every should-refuse dev case it answered (missed refusal OR answered with invented content)
                proposals.append((p, [v["id"] for v in dev_fail if v["should_refuse"]]))

        def critic(item):
            sid, vs = item
            # deterministic: most frequent category, ties broken by name (a set's order varies between processes)
            cats = sorted({v["failure"]["category"] for v in vs})
            cat = max(cats, key=lambda c: (sum(1 for v in vs if v["failure"]["category"] == c), [-ord(ch) for ch in c]))
            return critic_result(sid, vs, cat)

        def critic_result(sid, vs, cat):
            p = _critic_patch(run, current, sid, cat, vs, cases_by_id, responses)
            return (p, [v["id"] for v in vs]) if p else None

        for r in run.pmap(critic, list(by_section.items())):
            if r:
                proposals.append(r)

        accepted = []
        for n, (p, targets) in enumerate(proposals, 1):
            g = _gate(run, p, verdicts, targets, dev_cases, cases_by_id)
            p["gate"] = g
            p["id"] = f"P{it}.{n}"
            p["addresses"] = targets
            mark = C.style("accepted", "green") if g["accepted"] else C.style("rejected", "yellow")
            C.info(f"{p['id']} {p['target']:<24} fixes {len(g['fixed'])}, breaks {len(g['broke'])} on "
                   f"{len(g['subset'])} gated cases -> {mark}")
            C.info(C.style(f"      {truncate(p['change_summary'], 150)}", "grey"))
            if g["accepted"]:
                accepted.append(p)
        if not accepted:
            rec = {"iteration": it, "decision": "stopped: no proposed fix improved its targeted dev cases",
                   "patches": [_log_patch(p, False) for p, _ in proposals]}
            for p, _ in proposals:
                append_jsonl(log_path, {**_log_patch(p, False), "iteration": it})
            history.append(rec)
            C.warn("no candidate patch survived its regression gate - stopping (an honest stop beats a forced change)")
            break
        if run.gw.budget_left() < 0.1:
            C.warn("budget nearly exhausted before the re-evaluation - stopping with the last measured agent")
            history.append({"iteration": it, "decision": "stopped: budget", "patches": [_log_patch(p, False) for p, _ in proposals]})
            break
        merged = _merge(current, accepted)
        merged["version"] = current.get("version", 0) + 1
        merged.setdefault("provenance", {}).setdefault("changes", [])
        merged["provenance"]["changes"] = current.get("provenance", {}).get("changes", []) + [p["id"] for p in accepted]
        new_eval = evaluate(run, merged, cases, f"iteration {it}", run.path("06_iterations", f"iter_{it}"))
        before_dev = {v["id"]: v["pass"] for v in cur_eval["verdicts"] if v["split"] == "dev"}
        after_dev = {v["id"]: v["pass"] for v in new_eval["verdicts"] if v["split"] == "dev"}
        flips = paired_flips(before_dev, after_dev)
        sc_b, sc_a = cur_eval["scorecard"], new_eval["scorecard"]
        gain = (sc_a["dev"]["rate"] or 0) - (sc_b["dev"]["rate"] or 0)
        keep = flips["net"] > 0
        decision = "kept" if keep else "reverted (dev did not improve after merging patches)"
        for p in proposals:
            p_entry = _log_patch(p[0], p[0] in accepted)
            p_entry.update(iteration=it, score_before={"dev": sc_b["dev"], "holdout": sc_b["holdout"]},
                           score_after={"dev": sc_a["dev"], "holdout": sc_a["holdout"]} if p[0] in accepted else None,
                           iteration_decision=decision)
            append_jsonl(log_path, p_entry)
        history.append({"iteration": it, "label": f"iteration {it}", "scorecard": sc_a, "decision": decision,
                        "patches": [_log_patch(p, p in accepted) for p, _ in proposals],
                        "dev_flips": flips, "fingerprint": D.fingerprint(merged),
                        "seconds": round(time.time() - t0, 1), "fresh_tokens": run.gw.meter.fresh_tokens - tok0})
        C.ok(f"iteration {it}: dev {sc_b['dev']['passed']}/{sc_b['dev']['n']} -> {sc_a['dev']['passed']}/{sc_a['dev']['n']}"
             f"  holdout {sc_b['holdout']['passed']}/{sc_b['holdout']['n']} -> {sc_a['holdout']['passed']}/{sc_a['holdout']['n']}"
             f"  (fixed {len(flips['fixed'])}, broke {len(flips['broke'])}, McNemar p={flips['p_value']:.2f}) -> {decision}")
        if keep:
            current, cur_eval = merged, new_eval      # only ever moves to a strictly better dev score
            D.save(merged, run.path("agent", "history", f"v{merged['version']}.json"))
            if gain < s.min_gain:
                C.info(f"gain {gain:+.0%} < min_gain {s.min_gain:.0%}: further iterations unlikely to pay for themselves")
                history[-1]["decision"] += "; stopped: diminishing returns"
                break
        else:
            break
    current, cur_eval = prune_tools(run, current, cases, cur_eval, history, log_path)
    write_json(run.path("07_iterations.json"), history)
    return current, history, cur_eval


def prune_tools(run: Run, defn: dict, cases: list[dict], cur_eval: dict, history: list, log_path: Path):
    """Empirical tool audit: a tool that no eval case needs and the agent never
    called is removed - if removing it does not cost a single dev case."""
    used = {t["tool"] for r in cur_eval["responses"] for t in r.get("tool_calls", [])}
    expected = {c["expected"].get("tool") for c in cases}
    unused = [t["name"] for t in defn.get("tools", []) if t["name"] not in used and t["name"] not in expected]
    if not unused:
        return defn, cur_eval
    C.stage("7.t", f"Tool audit: {', '.join(unused)} attached but never used")
    nd = copy.deepcopy(defn)
    nd["tools"] = [t for t in nd["tools"] if t["name"] not in unused]
    nd["version"] = defn.get("version", 0) + 1
    new_eval = evaluate(run, nd, cases, "tool audit", run.path("06_iterations", "tool_audit"))
    b = {v["id"]: v["pass"] for v in cur_eval["verdicts"] if v["split"] == "dev"}
    a = {v["id"]: v["pass"] for v in new_eval["verdicts"] if v["split"] == "dev"}
    flips = paired_flips(b, a)
    keep = not flips["broke"] or flips["net"] > 0
    patch = {"id": "PT.1", "target": "tools", "category": "prompt_defect",
             "diagnosis": f"{', '.join(unused)} never called in {len(cur_eval['responses'])} evaluated questions",
             "change_summary": f"remove unused tool(s): {', '.join(unused)}", "before": [t["name"] for t in defn["tools"]],
             "after": [t["name"] for t in nd["tools"]], "addresses": [],
             "gate": {"subset": sorted(b), "fixed": flips["fixed"], "broke": flips["broke"], "accepted": keep}}
    append_jsonl(log_path, {**_log_patch(patch, keep), "iteration": "tool-audit"})
    sc_b, sc_a = cur_eval["scorecard"], new_eval["scorecard"]
    history.append({"iteration": "tool audit", "label": "tool audit", "scorecard": sc_a,
                    "decision": "kept (tool removed)" if keep else "reverted (removal cost dev cases)",
                    "patches": [_log_patch(patch, keep)], "dev_flips": flips, "fingerprint": D.fingerprint(nd)})
    C.ok(f"remove {', '.join(unused)}: dev {sc_b['dev']['passed']}/{sc_b['dev']['n']} -> {sc_a['dev']['passed']}/"
         f"{sc_a['dev']['n']} -> {'removed' if keep else 'kept (removal hurt)'}")
    if keep:
        D.save(nd, run.path("agent", "history", f"v{nd['version']}.json"))
        return nd, new_eval
    return defn, cur_eval


def _log_patch(p: dict, accepted: bool) -> dict:
    return {"id": p.get("id"), "target": p["target"], "category": p["category"], "diagnosis": p["diagnosis"],
            "change_summary": p["change_summary"], "addresses": p.get("addresses", []),
            "gate": {k: v for k, v in p.get("gate", {}).items()}, "accepted": accepted,
            "before": p["before"], "after": p["after"]}
