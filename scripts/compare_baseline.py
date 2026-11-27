"""Factory vs hand-written agent on the same generated eval set.

    forge eval demos/hr-shore-staff/run --agent demos/hr-shore-staff/human_baseline/agent.json
    python scripts/compare_baseline.py

Moves the newest eval re-run into human_baseline/eval and writes COMPARISON.md
with a paired (McNemar) comparison.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forgeai.util.stats import paired_flips, wilson  # noqa: E402

RUN = ROOT / "demos/hr-shore-staff/run"
OUT = ROOT / "demos/hr-shore-staff/human_baseline"


def rows(p: Path) -> dict:
    return {json.loads(x)["id"]: json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()}


def score(V: dict, split: str | None = None) -> str:
    vs = [v for v in V.values() if split is None or v["split"] == split]
    k = sum(v["pass"] for v in vs)
    lo, hi = wilson(k, len(vs))
    return f"{k}/{len(vs)} ({100 * k / len(vs):.0f}%, CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def main() -> int:
    reruns = sorted((RUN / "eval_reruns").glob("*")) if (RUN / "eval_reruns").exists() else []
    if reruns:
        dst = OUT / "eval"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(reruns[-1], dst)
        shutil.rmtree(RUN / "eval_reruns")
    cases = {c["id"]: c for c in json.loads((RUN / "05_evalset.json").read_text(encoding="utf-8"))["cases"]}
    fac, hum = rows(RUN / "09_final_verdicts.jsonl"), rows(OUT / "eval" / "verdicts.jsonl")
    fl = paired_flips({k: v["pass"] for k, v in fac.items()}, {k: v["pass"] for k, v in hum.items()})
    hall = lambda V: sum(1 for v in V.values() if v["failure"] and v["failure"]["category"] == "hallucination")  # noqa: E731
    L = ["# Factory vs human baseline (HR demo)", "",
         "Same brief, documents, model (`qwen3:8b`), runtime and judge. The **only** difference is who wrote the agent "
         "definition: the factory (`demos/hr-shore-staff/run/agent/agent.json`, from one paragraph) or the developer by hand "
         "(`agent.json` in this folder). Both are scored on the factory's generated eval set.", "",
         "| | Factory | Hand-written |", "|---|---|---|",
         f"| All cases | {score(fac)} | {score(hum)} |", f"| Dev | {score(fac, 'dev')} | {score(hum, 'dev')} |",
         f"| Holdout | {score(fac, 'holdout')} | {score(hum, 'holdout')} |",
         f"| Hallucination failures | {hall(fac)} | {hall(hum)} |", "",
         f"Paired comparison: the hand-written agent passes {len(fl['fixed'])} case(s) the factory fails and fails "
         f"{len(fl['broke'])} the factory passes (exact McNemar p = {fl['p_value']:.2f}).", "", "## Where they differ", ""]
    for cid in fl["fixed"] + fl["broke"]:
        c, f, h = cases[cid], fac[cid], hum[cid]
        who = "hand-written wins" if cid in fl["fixed"] else "factory wins"
        why = (f["failure"] if cid in fl["fixed"] else h["failure"]) or {}
        L.append(f"- **{cid}** ({c['kind']}, {c['split']}) - {who}. *{c['question']}*  \n  Loser's failure: "
                 f"{why.get('category', '')} - {why.get('detail', '')}")
    if not fl["fixed"] and not fl["broke"]:
        L.append("- No case differs.")
    L += ["", "## Reading", "",
          "- The hand-written prompt names the three policies, lists every sub-topic and tells the agent to answer the "
          "covered part of a partly covered question: domain knowledge a careful engineer brings after reading all three documents.",
          "- The factory produced its agent from one paragraph with no human effort, and also flagged the unsupported "
          "topics, wrote and verified the tests, and audited its own judge - none of which exists for the hand-written agent.",
          "- Caveat: the baseline's author had seen generated cases from earlier development runs on these documents, "
          "so the comparison slightly favours the baseline."]
    (OUT / "COMPARISON.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
