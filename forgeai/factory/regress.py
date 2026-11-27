"""Regression mode: the documents changed - what broke?

Rebuilds the agent against the new documents with the ORIGINAL requirements
(no new interview), re-runs the groundability audit (new gaps are reported),
then runs the OLD eval set against the regenerated agent. Each old case is
first re-validated against the new corpus, so the report separates:

  broke        - still valid (its facts are still in the documents) and now fails
  fixed        - failed before, passes now
  invalidated  - the documents changed the answer (a key fact disappeared);
                 the case is stale, not the agent
  unchanged    - same outcome
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from forgeai.config import Settings
from forgeai.factory import generator, groundability
from forgeai.factory.context import Run, make_gateway
from forgeai.factory.evaluate import evaluate
from forgeai.ingest import chunk_documents, load_folder
from forgeai.retrieval.index import KnowledgeIndex
from forgeai.runtime import definition as D
from forgeai.util import console as C
from forgeai.util.io import atomic_write_text, read_json, read_jsonl, write_json
from forgeai.util.text import fact_match, truncate


def regress(old_dir: Path, new_docs: Path, s: Settings) -> int:
    old_dir = Path(old_dir)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = old_dir.parent / f"{old_dir.name}-regress-{stamp}"
    gw = make_gateway(s, out)
    run = Run(settings=s, run_dir=out, gw=gw, docs_dir=Path(new_docs).resolve())
    C.out(C.style("ForgeAI regression mode", "bold") + f"  old run {old_dir.as_posix()}  new docs {Path(new_docs).as_posix()}")
    run.requirements = read_json(old_dir / "02_requirements.json")
    run.brief = (old_dir / "brief.md").read_text(encoding="utf-8").strip()
    old_defn = D.load(old_dir / "agent" / "agent.json")
    cases = read_json(old_dir / "05_evalset.json")["cases"]
    old_final = {v["id"]: v for v in read_jsonl(_final_verdicts(old_dir))}

    C.stage(1, "Reading the changed documents")
    run.docs, run.skipped = load_folder(run.docs_dir)
    old_docs = {d["path"]: d["sha256"] for d in old_defn["knowledge"]["documents"]}
    new_docs_map = {d.path: d.sha256 for d in run.docs}
    changes = {"added": sorted(set(new_docs_map) - set(old_docs)), "removed": sorted(set(old_docs) - set(new_docs_map)),
               "modified": sorted(p for p in set(old_docs) & set(new_docs_map) if old_docs[p] != new_docs_map[p])}
    for k, v in changes.items():
        for p in v:
            C.info(f"{k:<9} {p}")
    run.chunks = chunk_documents(run.docs)
    run.index = KnowledgeIndex.build(run.chunks, gw)

    C.stage(2, "Re-auditing groundability with the original requirements")
    g = groundability.check(run)
    old_g = read_json(old_dir / "03_groundability.json")
    old_v = {t["topic"]: t["verdict"] for t in old_g["topics"]}
    moved = [(t["topic"], old_v.get(t["topic"]), t["verdict"]) for t in g["topics"] if old_v.get(t["topic"]) != t["verdict"]]
    for topic, a, b in moved:
        C.warn(f"{topic}: {a} -> {b}")

    C.stage(3, "Regenerating the agent (same requirements, same prompt; knowledge and tools refreshed)")
    new_defn = D.load(old_dir / "agent" / "agent.json")
    new_defn["knowledge"]["documents"] = [{"doc_id": d.doc_id, "path": d.path, "kind": d.kind, "sha256": d.sha256}
                                         for d in run.docs]
    new_defn["refusal_policy"]["unsupported_topics"] = [x["topic"] for x in g["gaps"]]
    new_defn["version"] = old_defn.get("version", 0) + 1
    new_defn.setdefault("provenance", {})["regenerated_from"] = old_dir.as_posix()

    C.stage(4, "Re-validating the old eval set against the new documents")
    corpus_texts = [c.text for c in run.chunks]
    status = {}
    for c in cases:
        facts = c["expected"].get("key_facts", [])
        gone = [f["text"] for f in facts if not any(fact_match(f["text"], t)[0] == "match" for t in corpus_texts)]
        status[c["id"]] = {"valid": not gone, "missing_facts": gone}
    inval = [i for i, s_ in status.items() if not s_["valid"]]
    C.info(f"{len(inval)} case(s) invalidated by document changes: {', '.join(inval) or 'none'}")

    C.stage(5, "Running the old eval set on the regenerated agent")
    res = evaluate(run, new_defn, cases, "regression", out / "eval")
    rows = []
    for v in res["verdicts"]:
        before = old_final.get(v["id"], {}).get("pass")
        st = status[v["id"]]
        if not st["valid"]:
            outcome = "invalidated"
        elif before and not v["pass"]:
            outcome = "broke"
        elif before is False and v["pass"]:
            outcome = "fixed"
        else:
            outcome = "unchanged-pass" if v["pass"] else "unchanged-fail"
        rows.append({"id": v["id"], "kind": v["kind"], "before": before, "after": v["pass"], "outcome": outcome,
                     "missing_facts": st["missing_facts"], "failure": v["failure"]})
    generator.save_agent(run, new_defn, out / "agent")
    write_json(out / "regression.json", {"doc_changes": changes, "groundability_changes": moved, "cases": rows,
                                         "scorecard": res["scorecard"]})
    counts = {k: sum(1 for r in rows if r["outcome"] == k) for k in
              ("broke", "fixed", "invalidated", "unchanged-pass", "unchanged-fail")}
    by_id = {c["id"]: c for c in cases}
    L = ["# Regression report", "", f"Old run: `{old_dir.as_posix()}`  ", f"New documents: `{Path(new_docs).as_posix()}`", "",
         "## Document changes", ""]
    L += [f"- {k}: {', '.join(v) or 'none'}" for k, v in changes.items()]
    L += ["", "## Groundability changes", ""] + ([f"- {t}: {a} -> {b}" for t, a, b in moved] or ["- none"])
    L += ["", "## Outcome of the old eval set", "", "| Outcome | Cases |", "|---|---|"]
    L += [f"| {k} | {n} |" for k, n in counts.items()]
    L += ["", "| Case | Kind | Before | After | Outcome | Detail |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["outcome"] in ("unchanged-pass",):
            continue
        det = ("fact no longer in documents: " + "; ".join(r["missing_facts"])) if r["missing_facts"] else \
            (r["failure"]["detail"] if r["failure"] else "")
        L.append(f"| {r['id']} | {r['kind']} | {r['before']} | {r['after']} | **{r['outcome']}** | "
                 f"{truncate(by_id[r['id']]['question'], 60)} - {truncate(det, 100)} |")
    L += ["", "Invalidated cases are stale tests, not agent failures: regenerate the eval set for the new documents "
          "(`forge build`) to replace them."]
    atomic_write_text(out / "REGRESSION.md", "\n".join(L) + "\n")
    C.out()
    C.ok(f"broke {counts['broke']}, fixed {counts['fixed']}, invalidated {counts['invalidated']}  ->  "
         f"{(out / 'REGRESSION.md').as_posix()}")
    return 0


def _final_verdicts(old_dir: Path) -> Path:
    return old_dir / "09_final_verdicts.jsonl"
