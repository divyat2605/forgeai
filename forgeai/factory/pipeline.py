"""End-to-end factory run: brief + documents -> tested agent + honest report.

Every stage writes its artifact into the run folder as it finishes:

  brief.md, manifest.json
  01_corpus.json                 documents, profiles, skipped files
  02_requirements.json / .md     interview + requirements (+ human checkpoint)
  03_groundability.json / .md    per-topic verdicts with verified evidence
  04_tool_decisions.json         every tool considered, gates, reasons
  05_evalset.json                generated cases + self-check statistics
  06_tournament/                 candidate prompts scored on dev
  06_iterations/iter_k/          responses, verdicts, scorecard per iteration
  07_changes.jsonl               every patch: what, why, cases, gate, before/after
  07_iterations.json             iteration history and decisions
  08_judge_canaries.json         the judge's own accuracy
  agent/agent.json + knowledge/  the runnable agent (load with `forge chat`)
  agent/history/vN.json          every accepted version
  REPORT.md, report.json         the honest report
  trace.jsonl, llm_cache.sqlite  every model call; enables `forge replay`
"""

from __future__ import annotations

import datetime as _dt
import platform
import shutil
import sys
import time
from pathlib import Path

from forgeai import __version__
from forgeai.config import Settings, family
from forgeai.factory import evalgen, generator, groundability, intake, optimizer, report
from forgeai.factory.context import Run, make_gateway
from forgeai.factory.evaluate import evaluate
from forgeai.factory.judge import Judge, canaries
from forgeai.ingest.chunker import chunk_documents
from forgeai.ingest.loaders import load_folder
from forgeai.llm.gateway import BudgetExceeded
from forgeai.llm.prompts import all_prompt_hashes
from forgeai.retrieval.index import KnowledgeIndex
from forgeai.runtime import definition as D
from forgeai.util import console as C
from forgeai.util.io import atomic_write_text, rel_posix, read_json, sha256_file, slugify, write_json, write_jsonl

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


class NotGroundable(RuntimeError):
    pass


def _manifest(run: Run, status: str, extra: dict | None = None) -> None:
    files = {}
    for p in sorted(run.run_dir.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".jsonl", ".md") and "history" not in p.parts:
            files[p.relative_to(run.run_dir).as_posix()] = sha256_file(p)[:16]
    write_json(run.run_dir / "manifest.json", {
        "forgeai_version": __version__, "status": status,
        "started": run.__dict__.get("_now").isoformat() if run.__dict__.get("_now") else None,
        "platform": {"python": sys.version.split()[0], "os": platform.platform(), "machine": platform.machine()},
        "settings": run.settings.public(),
        "docs_dir": rel_posix(run.docs_dir, run.run_dir) if run.docs_dir else None,
        "answers_file": run.__dict__.get("_answers_file"),
        "documents": [{"path": d.path, "sha256": d.sha256} for d in run.docs],
        "prompt_sha256": all_prompt_hashes(),
        "meter": run.gw.meter.snapshot(),
        "stage_seconds": run.timings,
        "artifact_sha256": files,
        **(extra or {}),
    })


def _timed(run: Run, name: str):
    class T:
        def __enter__(self):
            self.t = time.time()

        def __exit__(self, *a):
            run.timings[name] = round(time.time() - self.t, 1)
    return T()


def build(settings: Settings, brief: str, docs_dir: Path, out_root: Path = Path("runs"), name: str | None = None,
          answers_file: Path | None = None, force: bool = False, backend=None, run_dir: Path | None = None,
          now: _dt.datetime | None = None) -> Path:
    settings.resolve()
    docs_dir = Path(docs_dir).resolve()
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"documents folder not found: {docs_dir}")
    stamp = (now or _dt.datetime.now(IST)).strftime("%Y%m%d-%H%M%S")
    run_dir = Path(run_dir) if run_dir else Path(out_root) / f"{name or slugify(brief, 32)}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    # a run folder must hold only this run's artifacts: clear leftovers (the replay cache and recorded
    # tool results are kept, they are inputs), so appended logs never mix two runs
    import shutil as _sh
    if any(run_dir.iterdir()) and not (run_dir / "manifest.json").exists() and not (run_dir / "llm_cache.sqlite").exists():
        raise FileExistsError(f"{run_dir} is not empty and is not a ForgeAI run folder - refusing to write into it")
    for p in list(run_dir.iterdir()):
        if p.name in ("llm_cache.sqlite", "tool_record.json", "_answers.json"):
            continue
        _sh.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    gw = make_gateway(settings, run_dir, backend=backend)
    run = Run(settings=settings, run_dir=run_dir, gw=gw, brief=brief.strip(), docs_dir=docs_dir)
    run.__dict__["_now"] = now or _dt.datetime.now(IST)
    if (run_dir / "tool_record.json").exists():
        run.__dict__["_tool_record"] = read_json(run_dir / "tool_record.json")
    atomic_write_text(run.path("brief.md"), brief.strip() + "\n")
    C.out(C.style(f"ForgeAI {__version__}", "bold") + f"  run {C.style(run_dir.as_posix(), 'cyan')}")
    C.info(f"factory {settings.factory_model} | agent {settings.agent_model} | judge {settings.judge_model} | "
           f"embed {settings.embed_model} | {settings.backend}{' | REPLAY' if settings.replay else ''}")
    if family(settings.agent_model) == family(settings.judge_model):
        C.warn("judge and agent are the same model family: self-preference risk (use --judge-model)")
    run.__dict__["_answers_file"] = rel_posix(answers_file, run_dir) if answers_file else None
    _manifest(run, "running")
    try:
        return _build(run, answers_file, force)
    except KeyboardInterrupt:
        _manifest(run, "interrupted")
        C.warn("interrupted - partial artifacts kept; re-run the same command with --resume to continue from cache")
        raise
    except BudgetExceeded:
        _manifest(run, "budget_exhausted")
        C.fail("budget exhausted before the run could finish (raise --max-minutes / --max-tokens)")
        raise
    finally:
        gw.cache.close() if gw.cache else None


def _build(run: Run, answers_file: Path | None, force: bool) -> Path:
    s = run.settings
    # ------------------------------------------------------------ 1. ingest
    C.stage(1, "Reading the document folder")
    with _timed(run, "ingest"):
        run.docs, run.skipped = load_folder(run.docs_dir)
        if not run.docs:
            raise NotGroundable(f"no readable documents in {run.docs_dir} ({len(run.skipped)} skipped)")
        run.chunks = chunk_documents(run.docs)
        run.index = KnowledgeIndex.build(run.chunks, run.gw)
    for d in run.docs:
        extra = f"table {len(d.table.rows)} rows x {len(d.table.columns)} cols" if d.table else f"{d.n_chars:,} chars"
        C.ok(f"{d.path:<44} {d.kind:<5} {extra}")
        for w in d.warnings:
            (C.info if w.startswith("removed") else C.warn)(f"{d.path}: {w}")
    for sk in run.skipped:
        C.warn(f"skipped {sk['path']}: {sk['reason']}")
    C.info(f"{len(run.chunks)} chunks indexed ({'hybrid BM25 + ' + s.embed_model if run.index.unit is not None else 'BM25 only'})")

    # ------------------------------------------------------- 2. interview
    C.stage(2, "Intake interview")
    with _timed(run, "intake"):
        intake.profile_corpus(run)
        req = intake.interview(run, answers_file)
    C.ok(f"requirements: {req['agent_name']} - {len(req['must_answer'])} must-answer, "
         f"{len(req['must_refuse'])} must-refuse topics; {len(req.get('interview', []))} question(s) asked")

    # --------------------------------------------------- 3. groundability
    C.stage(3, "Groundability guard")
    with _timed(run, "groundability"):
        g = groundability.check(run)
    for t in g["topics"]:
        col = {"supported": "green", "tool": "green", "partial": "yellow", "unsupported": "red"}[t["verdict"]]
        C.info(C.style(f"{t['verdict'].upper():<12}", col) + f" {t['topic']}" +
               (C.style(f"  (overridden: model said {t['model_verdict']})", "grey") if t["notes"] else ""))
    atomic_write_text(run.path("03_groundability.md"), groundability.markdown(g))
    atomic_write_text(run.path("02_requirements.md"), intake.requirements_markdown(req, req.get("interview"), g))
    if g["gaps"]:
        C.warn(f"{len(g['gaps'])} required topic(s) are NOT supported by the documents: "
               + "; ".join(x["topic"] for x in g["gaps"]) + " -> the agent will decline them")
    if g["coverage"] < 0.25 and not force:
        _manifest(run, "stopped_not_groundable")
        atomic_write_text(run.path("REPORT.md"),
                          "# ForgeAI stopped: brief not groundable\n\nThe documents support only "
                          f"{g['coverage']:.0%} of the required topics, so any agent built from them would have to "
                          "invent its answers. No agent was generated.\n\n" + groundability.markdown(g) +
                          "\nAdd documents that cover the gaps, narrow the brief, or re-run with `--force`.\n")
        C.fail(f"coverage {g['coverage']:.0%}: refusing to build an agent that would hallucinate the gap away "
               "(see REPORT.md; --force overrides)")
        raise NotGroundable("documents do not support the brief")

    # -------------------------------------------------------- 4. generate
    C.stage(4, "Generating the agent definition")
    styles = list(generator.STYLES) if s.tournament else ["rules"]
    if s.max_minutes and len(styles) > 1 and (s.max_minutes < 25 or run.gw.budget_left() < 0.6):
        styles = ["rules"]
        C.info("time budget is tight: prompt tournament skipped (single 'rules' prompt)")
    with _timed(run, "generate"):
        cands, tool_decisions = generator.generate(run, styles)

    # --------------------------------------------------------- 5. evalgen
    C.stage(5, "Generating the evaluation set")
    if s.max_minutes and s.max_minutes < 30 and s.eval_target > 24:
        s.eval_target = 24
        C.info("time budget is tight: eval set sized to 24 cases")
    with _timed(run, "evalgen"):
        ev = evalgen.generate(run, cands[0])
    st = ev["stats"]
    C.ok(f"{st['total']} verified cases: " + ", ".join(f"{k} {v}" for k, v in sorted(st["by_kind"].items())) +
         f"  |  dev {st['dev']} / holdout {st['holdout']}")
    dropped = {k: v for k, v in st["checks"].items() if k.startswith("dropped") and v}
    if dropped:
        C.info("self-checks dropped: " + ", ".join(f"{k[8:]} {v}" for k, v in dropped.items()))
    cases = ev["cases"]

    # ------------------------------------------------------ 6. tournament
    tour = None
    if len(cands) > 1:
        C.stage(6, f"Prompt tournament ({len(cands)} candidates, scored on dev)")
        with _timed(run, "tournament"):
            agent0, tour = optimizer.tournament(run, cands, cases)
        C.ok(f"winner: {agent0['system_prompt']['style']}")
    else:
        agent0 = cands[0]
    D.save(agent0, run.path("agent", "history", "v0.json"))

    # ------------------------------------------------- 7. evaluate + loop
    C.stage(7, "Baseline evaluation (iteration 0)")
    with _timed(run, "baseline_eval"):
        base = evaluate(run, agent0, cases, "iteration 0", run.path("06_iterations", "iter_0"))
    sc = base["scorecard"]
    C.ok(f"dev {sc['dev']['passed']}/{sc['dev']['n']}  holdout {sc['holdout']['passed']}/{sc['holdout']['n']}  "
         f"failures: " + (", ".join(f"{k} {v}" for k, v in sc["failures"].items()) or "none"))
    with _timed(run, "optimize"):
        try:
            final_defn, history, final_eval = optimizer.optimize(run, agent0, cases, base)
        except BudgetExceeded:
            C.warn("budget ceiling hit inside the optimizer - shipping the baseline agent")
            final_defn, final_eval = agent0, base
            history = [{"iteration": 0, "label": "baseline", "scorecard": base["scorecard"], "patches": [],
                        "decision": "baseline (optimizer stopped by budget)", "fingerprint": D.fingerprint(agent0)}]

    # ---------------------------------------------------------- 8. judge
    C.stage(8, "Auditing the judge (canaries with known verdicts)")
    with _timed(run, "judge_audit"):
        try:
            can = canaries(Judge(run.gw, stage="canary"), cases)
        except BudgetExceeded:
            can = {"n_canaries": 0, "overall": None, "skipped": "budget"}
    write_json(run.path("08_judge_canaries.json"), can)
    if can.get("overall") is not None:
        C.ok(f"judge accuracy on {can['n_canaries']} canaries: {can['overall']:.0%} "
             f"(verbosity effect {100 * can.get('verbosity_effect', 0):+.0f} pts)")

    # --------------------------------------------------------- 9. ship
    C.stage(9, "Shipping the agent and the report")
    agent_path = generator.save_agent(run, final_defn)
    write_json(run.path("tool_record.json"), run.__dict__.get("_tool_record", {}))
    _manifest(run, "complete")
    summary = report.write(run.run_dir, {
        "brief": run.brief, "requirements": run.requirements, "groundability": run.groundability,
        "evalset": ev, "tool_decisions": tool_decisions, "history": history, "final_eval": final_eval,
        "canaries": can, "agent": final_defn, "meter": run.gw.meter.snapshot(), "settings": s.public(),
        "tournament": tour, "run_name": run.run_dir.as_posix()})
    write_json(run.path("09_final_scorecard.json"), final_eval["scorecard"])
    write_jsonl(run.path("09_final_verdicts.jsonl"), final_eval["verdicts"])
    write_jsonl(run.path("09_final_responses.jsonl"), final_eval["responses"])
    _manifest(run, "complete", {"agent": rel_posix(agent_path, run.run_dir)})
    h, d = summary["holdout"], summary["dev"]
    C.out()
    C.out(C.style("  RESULT", "bold") + f"  holdout {h['passed']}/{h['n']} ({100 * (h['rate'] or 0):.0f}%, "
          f"95% CI {100 * h['ci95'][0]:.0f}-{100 * h['ci95'][1]:.0f}%)   dev {d['passed']}/{d['n']}   "
          f"remaining failures: " + (", ".join(f"{k} {v}" for k, v in summary["failures_final"].items()) or "none"))
    C.out(f"  report  {(run.run_dir / 'REPORT.md').as_posix()}")
    C.out(f"  chat    forge chat {run.run_dir.as_posix()}")
    return run.run_dir


def resume_dir(path: Path) -> dict:
    return read_json(Path(path) / "manifest.json")


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)
