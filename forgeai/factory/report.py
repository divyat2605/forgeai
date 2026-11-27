"""Stage 7 - Honest report.

Leads with the HOLDOUT score and its uncertainty, states what still fails and
why (by measured category, with the actual cases), shows every change the
optimizer made and whether it paid off, audits the judge itself, and lists the
limits of the evidence. Nothing here is written by a model: every sentence is
derived from recorded artifacts, so the report cannot flatter the factory.
"""

from __future__ import annotations

from collections import Counter

from forgeai.config import family
from forgeai.factory.judge import CATEGORIES
from forgeai.util.io import write_json, atomic_write_text
from forgeai.util.text import truncate


def _r(x: dict | None) -> str:
    if not x or not x.get("n"):
        return "n/a"
    return f"{x['passed']}/{x['n']} ({100 * x['rate']:.0f}%, CI {100 * x['ci95'][0]:.0f}-{100 * x['ci95'][1]:.0f}%)"


def _p(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def build(ctx: dict) -> tuple[str, dict]:
    req, g, ev, tools = ctx["requirements"], ctx["groundability"], ctx["evalset"], ctx["tool_decisions"]
    hist, final, canary, defn = ctx["history"], ctx["final_eval"], ctx["canaries"], ctx["agent"]
    meter, settings, tour = ctx["meter"], ctx["settings"], ctx.get("tournament")
    sc0 = hist[0]["scorecard"]
    scf = final["scorecard"]
    fails = [v for v in final["verdicts"] if not v["pass"]]
    cases = {c["id"]: c for c in ev["cases"]}
    resp = {r["case_id"]: r for r in final["responses"]}

    L: list[str] = []
    L += [f"# ForgeAI report: {req['agent_name']}", "",
          f"> **Brief.** {truncate(ctx['brief'], 400)}", ""]
    # ------------------------------------------------------------- headline
    L += ["## Headline", "",
          "| | Baseline (iteration 0) | Final agent |", "|---|---|---|",
          f"| **Holdout** (never seen by the optimizer) | {_r(sc0['holdout'])} | **{_r(scf['holdout'])}** |",
          f"| Dev (used to choose fixes) | {_r(sc0['dev'])} | {_r(scf['dev'])} |",
          f"| All cases | {_r(sc0['overall'])} | {_r(scf['overall'])} |", ""]
    gap = (scf["dev"]["rate"] or 0) - (scf["holdout"]["rate"] or 0)
    L.append(f"The holdout score is the number to trust. Dev minus holdout is {100 * gap:+.0f} points"
             + (" - a large gap means the fixes partly fitted the dev cases." if gap > 0.15 else
                " - no sign that the fixes over-fitted the dev cases." if gap <= 0.05 else "."))
    dh = (scf["holdout"]["passed"] or 0) - (sc0["holdout"]["passed"] or 0)
    dd = (scf["dev"]["passed"] or 0) - (sc0["dev"]["passed"] or 0)
    if dh < 0:
        L.append(f"Note the trade-off: the accepted changes fixed {dd:+d} dev case(s) but the holdout moved by {dh:+d}. "
                 "The holdout was never used to decide, so this is reported, not tuned away.")
    L.append(f"With {scf['holdout']['n']} holdout cases the 95% interval is wide; treat differences under "
             f"~{100 * (scf['holdout']['ci95'][1] - scf['holdout']['ci95'][0]) / 2:.0f} points as noise.")
    L.append("")

    # --------------------------------------------------------- still fails
    L += ["## What still fails, and why", ""]
    if not fails:
        L.append("Every generated case passes. That is a reason to suspect the eval set, not to celebrate: see "
                 "*Limits of this evidence*.")
    else:
        cats = Counter(v["failure"]["category"] for v in fails)
        for cat, n in cats.most_common():
            L.append(f"- **{cat.replace('_', ' ')} - {n} case(s).** {CATEGORIES[cat].capitalize()}.")
        L += ["", "| Case | Split | Kind | Category | Question | What happened |", "|---|---|---|---|---|---|"]
        for v in fails:
            c = cases[v["id"]]
            r = resp.get(v["id"], {})
            did = ("refused" if r.get("refused") else "answered") + ": " + truncate(r.get("answer", ""), 90)
            L.append(f"| {v['id']} | {v['split']} | {v['kind']} | {v['failure']['category']} | "
                     f"{truncate(c['question'], 80)} | {truncate(v['failure']['detail'], 110)} <br>*{did}* |".replace("\n", " "))
    L.append("")
    if g.get("gaps"):
        L += ["**Known gaps (flagged before generation).** The brief asks for these, but the documents do not "
              "support them. The agent is instructed to decline them, and the eval set tests that it does:", ""]
        L += [f"- {x['topic']}: {x['missing']}" for x in g["gaps"]]
        L.append("")

    # ---------------------------------------------------------- scorecard
    L += ["## Per-iteration scorecard", "",
          "| Iter | Dev | Holdout | Fact recall | Grounded | Retrieval recall | Correct refusals | False refusals | Decision |",
          "|---|---|---|---|---|---|---|---|---|"]
    for h in hist:
        sc = h.get("scorecard")
        if not sc:
            L.append(f"| {h['iteration']} | - | - | - | - | - | - | - | {h['decision']} |")
            continue
        m = sc["metrics"]
        L.append(f"| {h['iteration']} | {sc['dev']['passed']}/{sc['dev']['n']} | {sc['holdout']['passed']}/{sc['holdout']['n']} | "
                 f"{_p(m['fact_recall_mean'])} | {_p(m['grounded_rate'])} | {_p(m['retrieval_recall'])} | "
                 f"{_p(m['correct_refusal_rate'])} | {_p(m['false_refusal_rate'])} | {h['decision']} |")
    L += ["", "Failure categories by iteration (all cases):", "", "| Iter | " + " | ".join(CATEGORIES) + " |",
          "|---|" + "---|" * len(CATEGORIES)]
    for h in hist:
        if h.get("scorecard"):
            f = h["scorecard"]["failures"]
            L.append(f"| {h['iteration']} | " + " | ".join(str(f.get(c, 0)) for c in CATEGORIES) + " |")
    L.append("")

    # ---------------------------------------------------------- changes
    L += ["## Every change the optimizer tried", ""]
    any_patch = False
    for h in hist[1:]:
        for p in h.get("patches", []):
            any_patch = True
            gate = p.get("gate", {})
            L.append(f"- **{p['id']}** `{p['target']}` for *{p['category']}* "
                     f"(addresses {', '.join(p.get('addresses') or []) or '-'}): {p['change_summary']}  \n"
                     f"  Why: {p['diagnosis']}  \n"
                     f"  Gate: fixed {len(gate.get('fixed', []))}, broke {len(gate.get('broke', []))} -> "
                     f"**{'accepted' if p['accepted'] else 'rejected'}**; iteration {h['iteration']} {h['decision']}.")
    if not any_patch:
        L.append("No patches were needed or none were proposed.")
    L += ["", "Full before/after text of each change: `07_changes.jsonl`.", ""]

    # ------------------------------------------------------------- agent
    k = defn["knowledge"]
    L += ["## The agent that was built", "",
          f"- Definition: `agent/agent.json` (fingerprint `{scf['agent_fingerprint']}`, version {defn.get('version', 0)}); "
          "run it with `forge chat <this run folder>`.",
          f"- Model: `{defn['model']['name']}`, temperature {defn['model']['temperature']}.",
          f"- Knowledge: {len(k['documents'])} document(s); chunking {k['chunking']['max_chars']} chars / "
          f"{k['chunking']['overlap']} overlap; hybrid retrieval top_k={k['retrieval']['top_k']}, "
          f"bm25_weight={k['retrieval']['bm25_weight']}, neighbours={k['retrieval'].get('neighbours', 0)}, "
          f"query_rewrite={k['retrieval'].get('query_rewrite', False)}; abstention threshold "
          f"{defn['guards'].get('min_relevance', 0)}.",
          "", "**Tools.**", "", "| Tool | Attached | Model proposed | Final reason |", "|---|---|---|---|"]
    for t in tools:
        L.append(f"| {t['tool']} | {'yes' if t['attach'] else 'no'} | {'yes' if t['model_said'] else 'no'} | "
                 f"{truncate(t['final_reason'] or t['model_reason'], 140)} |")
    used = scf.get("tools_used", {})
    attached = [t["name"] for t in defn.get("tools", [])]
    unused = [t for t in attached if not used.get(t)]
    if attached:
        L.append("")
        L.append("Tool calls during the final evaluation: " + (", ".join(f"{k}: {v}" for k, v in used.items()) or "none")
                 + (f". Attached but never called: {', '.join(unused)}." if unused else "."))
    if tour:
        L += ["", "**Prompt tournament** (candidates scored on dev pointwise; no pairwise judging, so no position bias):", "",
              "| Style | Dev | Fact recall | Grounded | Prompt chars | |", "|---|---|---|---|---|---|"]
        for t in tour:
            L.append(f"| {t['style']} | {t['dev']['passed']}/{t['dev']['n']} | {_p(t['fact_recall'])} | {_p(t['grounded'])} | "
                     f"{t['prompt_chars']} | {'winner' if t['winner'] else ''} |")
    L.append("")

    # ---------------------------------------------------------- eval set
    st = ev["stats"]
    ch = st["checks"]
    L += ["## The generated eval set", "",
          f"{st['total']} cases ({st['dev']} dev / {st['holdout']} holdout, stratified by kind; re-phrased cases stay "
          f"in the same split as their origin). Kinds: " + ", ".join(f"{k} {v}" for k, v in sorted(st["by_kind"].items())) +
          f". {st['should_refuse']} must be refused.", "",
          "Self-checks applied while generating (cases dropped):", "",
          f"- key facts not found verbatim in the source passage: {ch.get('dropped_unverifiable_facts', 0)}",
          f"- vague questions that only make sense next to the source: {ch.get('dropped_vague_question', 0)}",
          f"- answerable without documents (closed-book leakage): {ch.get('dropped_parametric_leakage', 0)}",
          f"- 'must refuse' label contradicted by the corpus: {ch.get('dropped_refusal_label_wrong', 0)}",
          f"- near-duplicates: {ch.get('dropped_duplicate', 0)}",
          f"- failed re-phrasings / tool cases: {ch.get('dropped_edge_rephrase', 0)} / {ch.get('dropped_tool_case', 0)}",
          "", "Generation prompts: `forgeai/prompts/evalgen.*.md` (hashes in `manifest.json`).", ""]

    # -------------------------------------------------------------- judge
    agent_fam, judge_fam = family(settings["agent_model"]), family(settings["judge_model"])
    meth = Counter(f["method"] for v in final["verdicts"] for f in v.get("facts", []))
    cl = Counter(c["method"].split(":")[0] for v in final["verdicts"] for c in v.get("claims", []))
    L += ["## Can the judge be trusted?", "",
          f"- Judge model `{settings['judge_model']}` ({judge_fam}) vs agent `{settings['agent_model']}` ({agent_fam}): "
          + ("different families (limits self-preference)." if agent_fam != judge_fam else
             "**same family - self-preference risk; override --judge-model**."),
          f"- Fact verdicts: " + ", ".join(f"{k} {v}" for k, v in meth.most_common()) + ". "
          f"Claim verdicts: " + ", ".join(f"{k} {v}" for k, v in cl.most_common()) + ".",
          "- Position bias: not applicable by design (all judgements are pointwise).", ""]
    if canary and canary.get("n_canaries"):
        L += ["Canary audit: the judge scored answers whose correct verdict is known:", "",
              "| Canary | Judge accuracy |", "|---|---|",
              f"| correct answer accepted | {_p(canary['gold_pass'])} |",
              f"| wrong numbers / swapped facts rejected | {_p(canary['corrupted_fail'])} |",
              f"| same correct answer padded with filler still accepted (verbosity) | {_p(canary['padded_pass'])} |",
              f"| fabricated extra claim caught | {_p(canary['fabrication_caught'])} |",
              f"| **overall ({canary['n_canaries']} canaries)** | **{_p(canary['overall'])}** |", "",
              f"Verbosity effect (padded minus plain acceptance): {100 * canary.get('verbosity_effect', 0):+.0f} points.", ""]

    # ------------------------------------------------------------- limits
    L += ["## Limits of this evidence", "",
          f"- Small samples: {scf['overall']['n']} cases in total. Intervals are reported, and no claim here is "
          "stronger than they allow.",
          "- The eval set is generated by the same factory that built the agent. Verbatim fact checks, the leakage "
          "probe and label verification reduce this circularity, but they do not remove it. A human-written "
          "test set would be a stronger check.",
          "- Faithfulness checks compare each claim with the passages the agent saw. Correct general knowledge "
          "that is not in the sources is counted as unsupported, which is deliberate for a grounded agent.",
          "- Near-miss out-of-scope tests are the hardest to label: a question can be partly covered by the documents. "
          "Two model families must agree a topic is absent before such a test is kept, but a few labels may still be "
          "debatable; each is inspectable in `05_evalset.json` (`label_votes`).",
          "- Weather and date cases check that the tool was called, not the live values.", ""]

    # -------------------------------------------------------------- cost
    L += ["## Cost and reproducibility", "",
          f"- Wall time {meter['wall_seconds'] / 60:.1f} min; {meter['calls']} model calls ({meter['cache_hits']} served "
          f"from cache); {meter['tokens_in'] + meter['tokens_out']:,} fresh tokens; {meter['repairs']} schema "
          f"repairs; {meter['failures']} failed calls.",
          f"- Models: factory `{settings['factory_model']}`, agent `{settings['agent_model']}`, judge "
          f"`{settings['judge_model']}`, embeddings `{settings['embed_model']}` (backend {settings['backend']}).",
          "- Replay without any model: `forge replay <this run folder>` re-executes this run from `llm_cache.sqlite`.",
          ""]
    md = "\n".join(L) + "\n"
    summary = {
        "agent": req["agent_name"], "holdout": scf["holdout"], "dev": scf["dev"], "overall": scf["overall"],
        "baseline": {"holdout": sc0["holdout"], "dev": sc0["dev"]},
        "failures_final": scf["failures"], "metrics_final": scf["metrics"], "canaries": canary,
        "gaps": g.get("gaps", []), "tools": attached, "iterations": len(hist) - 1,
        "cost": {k: meter[k] for k in ("wall_seconds", "calls", "cache_hits", "tokens_in", "tokens_out")},
    }
    return md, summary


def write(run_dir, ctx: dict) -> dict:
    md, summary = build(ctx)
    atomic_write_text(run_dir / "REPORT.md", md)
    write_json(run_dir / "report.json", summary)
    return summary
