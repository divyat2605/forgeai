"""Eval harness: run an agent definition over cases, judge, and score.

Uses the very same AgentRuntime the chat runner uses. Scores are reported for
dev and holdout separately with Wilson 95% intervals; the optimizer only ever
reads dev failures.
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path

from forgeai.factory.context import Run
from forgeai.factory.generator import build_knowledge
from forgeai.factory.judge import Judge
from forgeai.runtime import definition as D
from forgeai.runtime.agent import AgentRuntime
from forgeai.runtime.tools import tables_from_docs
from forgeai.util.io import write_json, write_jsonl
from forgeai.util.stats import wilson


def runtime_for(run: Run, defn: dict, stage: str = "agent") -> AgentRuntime:
    _, index = build_knowledge(run, defn["knowledge"]["chunking"])
    rec = run.__dict__.setdefault("_tool_record", {})
    return AgentRuntime(defn, index, run.gw, tables_from_docs(run.docs), offline_tools=run.settings.offline_tools,
                        now=run.__dict__.get("_now"), stage=stage, tool_record=rec)


def _rate(vs: list[dict]) -> dict:
    k, n = sum(1 for v in vs if v["pass"]), len(vs)
    lo, hi = wilson(k, n)
    return {"passed": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


def scorecard(verdicts: list[dict], responses: list[dict], label: str, defn: dict) -> dict:
    dev = [v for v in verdicts if v["split"] == "dev"]
    hold = [v for v in verdicts if v["split"] == "holdout"]
    ans = [v for v in verdicts if not v["should_refuse"]]
    ref = [v for v in verdicts if v["should_refuse"]]
    recalls = [v["fact_recall"] for v in ans if v["fact_recall"] is not None]
    grounded = [v["grounded"] for v in ans if v["grounded"] is not None]
    gold = [v["gold_retrieved"] for v in ans if v["gold_retrieved"] is not None]
    lat = [r.get("latency_s", 0.0) for r in responses]
    cats = Counter(v["failure"]["category"] for v in verdicts if v["failure"])
    cats_dev = Counter(v["failure"]["category"] for v in dev if v["failure"])
    sub = Counter(f"{v['failure']['category']}/{v['failure']['subtype']}" for v in verdicts if v["failure"])
    kinds = sorted({v["kind"] for v in verdicts})
    tools_used = Counter(t["tool"] for r in responses for t in r.get("tool_calls", []))
    return {
        "label": label,
        "agent_fingerprint": D.fingerprint(defn),
        "overall": _rate(verdicts),
        "dev": _rate(dev),
        "holdout": _rate(hold),
        "by_kind": {k: _rate([v for v in verdicts if v["kind"] == k]) for k in kinds},
        "metrics": {
            "fact_recall_mean": round(statistics.mean(recalls), 3) if recalls else None,
            "grounded_rate": round(sum(grounded) / len(grounded), 3) if grounded else None,
            "retrieval_recall": round(sum(gold) / len(gold), 3) if gold else None,
            "correct_refusal_rate": round(sum(1 for v in ref if v["refused"]) / len(ref), 3) if ref else None,
            "false_refusal_rate": round(sum(1 for v in ans if v["refused"]) / len(ans), 3) if ans else None,
            "citation_rate": round(sum(1 for v in ans if v["cited"] and not v["refused"]) /
                                   max(1, sum(1 for v in ans if not v["refused"])), 3),
            "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
            "latency_p95_s": round(sorted(lat)[max(0, int(0.95 * len(lat)) - 1)], 2) if lat else None,
            "runtime_errors": sum(1 for r in responses if r.get("error")),
        },
        "failures": dict(cats),
        "failures_dev": dict(cats_dev),
        "failure_subtypes": dict(sub),
        "tools_used": dict(tools_used),
    }


def evaluate(run: Run, defn: dict, cases: list[dict], label: str, out_dir: Path | None = None,
             splits: tuple[str, ...] = ("dev", "holdout"), stage: str = "eval") -> dict:
    rt = runtime_for(run, defn, stage=f"{stage}.agent")
    judge = Judge(run.gw, stage=f"{stage}.judge")
    todo = [c for c in cases if c["split"] in splits]

    def one(case):
        resp = rt.answer(case["question"])
        return resp, judge.judge(case, resp)

    pairs = run.pmap(one, todo, f"{label}: running + judging {len(todo)} cases")
    responses = [p[0] for p in pairs]
    verdicts = [p[1] for p in pairs]
    for c, r in zip(todo, responses):
        r["case_id"] = c["id"]
    sc = scorecard(verdicts, responses, label, defn)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(out_dir / "responses.jsonl", responses)
        write_jsonl(out_dir / "verdicts.jsonl", verdicts)
        write_json(out_dir / "scorecard.json", sc)
    return {"scorecard": sc, "verdicts": verdicts, "responses": responses}


def retrieval_recall(run: Run, chunking: dict, retrieval: dict, cases: list[dict]) -> float:
    """Cheap, model-free proxy used by the optimizer: fraction of dev key facts
    that appear verbatim in the retrieved context (no generation needed)."""
    from forgeai.util.text import fact_match

    _, index = build_knowledge(run, chunking)
    hits_total, facts_total = 0, 0
    for c in cases:
        facts = c["expected"].get("key_facts", [])
        if not facts or c["expected"].get("tool") in ("weather", "current_date"):
            continue
        hits = index.search(c["question"], top_k=int(retrieval["top_k"]), bm25_weight=float(retrieval["bm25_weight"]),
                            gateway=run.gw, neighbours=int(retrieval.get("neighbours", 0)))
        texts = [h.chunk.text for h in hits]
        for f in facts:
            facts_total += 1
            if any(fact_match(f["text"], t)[0] == "match" for t in texts):
                hits_total += 1
    return hits_total / facts_total if facts_total else 1.0
