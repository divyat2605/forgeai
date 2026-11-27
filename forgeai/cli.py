"""ForgeAI command line.

  forge doctor                         check Python, Ollama, models; recommend a profile
  forge build --brief-file B --docs D  run the factory end to end (unattended with --unattended)
  forge chat RUN_OR_AGENT              chat with any produced agent (generic runner)
  forge eval RUN [--cases FILE]        re-run an eval set against a (possibly hand-edited) agent
  forge regress RUN --docs NEW         documents changed: rebuild, re-run the old eval set, report what broke
  forge replay RUN                     re-execute a committed run from its cache, no model needed
  forge ui                             ForgeAI Studio in the browser (no extra dependencies)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
import time
from pathlib import Path

from forgeai import __version__
from forgeai.config import PROFILES, Settings
from forgeai.util import console as C


def _settings_from(args) -> Settings:
    s = Settings(profile=args.profile, backend=args.backend, host=args.host or Settings().host)
    for k in ("factory_model", "agent_model", "judge_model", "embed_model"):
        v = getattr(args, k, None)
        if v:
            setattr(s, k, v)
    s.workers = args.workers
    s.max_minutes = args.max_minutes
    s.max_tokens = args.max_tokens
    s.max_iterations = min(3, args.max_iterations)
    s.eval_target = max(20, args.eval_size)
    s.interactive = not args.unattended
    s.approve_requirements = args.approve and not args.unattended
    s.tournament = not args.no_tournament
    s.offline_tools = args.offline
    s.seed = args.seed
    if args.cache_dir:
        s.cache_dir = Path(args.cache_dir)
    return s.resolve()


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("models")
    g.add_argument("--profile", default="standard", choices=sorted(PROFILES))
    g.add_argument("--backend", default="ollama", choices=["ollama", "openai"])
    g.add_argument("--host", default="", help="Ollama host or OpenAI-compatible base URL")
    g.add_argument("--factory-model", dest="factory_model")
    g.add_argument("--agent-model", dest="agent_model")
    g.add_argument("--judge-model", dest="judge_model")
    g.add_argument("--embed-model", dest="embed_model")
    g.add_argument("--workers", type=int, default=4, help="parallel model calls (match OLLAMA_NUM_PARALLEL)")
    g.add_argument("--cache-dir", default="")
    r = p.add_argument_group("run")
    r.add_argument("--max-minutes", type=float, default=0.0, help="time budget; the loop stops early when it runs low")
    r.add_argument("--max-tokens", type=int, default=0, help="fresh-token budget")
    r.add_argument("--max-iterations", type=int, default=3)
    r.add_argument("--eval-size", type=int, default=32)
    r.add_argument("--unattended", action="store_true", help="no questions: defaults are assumed and recorded")
    r.add_argument("--approve", action="store_true", help="human checkpoint: approve/edit requirements first")
    r.add_argument("--no-tournament", action="store_true")
    r.add_argument("--offline", action="store_true", help="disable network tools (weather)")
    r.add_argument("--seed", type=int, default=7)


def _resolve_agent(target: str) -> Path:
    p = Path(target)
    if p.is_dir():
        p = p / "agent" / "agent.json" if (p / "agent" / "agent.json").exists() else p / "agent.json"
    if not p.exists():
        raise SystemExit(f"no agent definition at {target}")
    return p


# ------------------------------------------------------------------- build
def cmd_build(args) -> int:
    from forgeai.factory.pipeline import NotGroundable, build

    if args.brief_file:
        brief = Path(args.brief_file).read_text(encoding="utf-8")
    elif args.brief:
        brief = args.brief
    else:
        C.out("Paste the one-paragraph brief, then an empty line:")
        lines = []
        for line in sys.stdin:
            if not line.strip():
                break
            lines.append(line.rstrip("\n"))
        brief = " ".join(lines)
    if not brief.strip():
        raise SystemExit("a brief is required (--brief or --brief-file)")
    s = _settings_from(args)
    run_dir = Path(args.resume) if args.resume else None
    try:
        build(s, brief, Path(args.docs), Path(args.out), args.name,
              Path(args.answers) if args.answers else None, force=args.force, run_dir=run_dir)
    except NotGroundable as e:
        C.fail(str(e))
        return 3
    return 0


# -------------------------------------------------------------------- chat
def _agent_gateway(defn: dict, args):
    from forgeai.factory.context import make_backend
    from forgeai.llm.cache import LayeredCache, SqliteStore
    from forgeai.llm.gateway import Gateway, RoleConfig

    s = Settings(backend=args.backend, host=args.host or Settings().host).resolve()
    be = make_backend(s)
    model = args.agent_model or defn["model"]["name"]
    roles = {"agent": RoleConfig(model, be, float(defn["model"].get("temperature", 0.0)),
                                 int(defn["model"].get("num_ctx", 8192)), int(defn["model"].get("max_tokens", 700)))}
    cache = LayeredCache([SqliteStore(Path(args.cache_dir or s.cache_dir) / "llm_cache.sqlite")])
    return Gateway(roles, embed_backend=be, embed_model=defn["knowledge"].get("embed_model", s.embed_model), cache=cache)


def cmd_chat(args) -> int:
    from forgeai.runtime import definition as D
    from forgeai.runtime.agent import AgentRuntime

    path = _resolve_agent(args.target)
    defn = D.load(path)
    gw = _agent_gateway(defn, args)
    rt = AgentRuntime.from_path(path, gw, offline_tools=args.offline)
    tools = ", ".join(t["name"] for t in defn.get("tools", [])) or "none"
    if not args.question:
        C.out(C.style(f"{defn['name']}", "bold") + f"  (model {gw.model_of('agent')}, tools: {tools})")
        C.out(C.style(f"  {defn.get('description', '')}", "grey"))
        C.out(C.style("  Type a question. /sources shows what was retrieved, /quit exits.", "grey"))
    history: list[dict] = []
    last = None
    questions = [args.question] if args.question else None
    while True:
        if questions is not None:
            if not questions:
                break
            q = questions.pop(0)
        else:
            try:
                q = input(C.style("\nyou> ", "bold")).strip()
            except (EOFError, KeyboardInterrupt):
                C.out()
                break
        if not q:
            continue
        if q in ("/quit", "/exit", "/q"):
            break
        if q == "/sources":
            for r in (last or {}).get("retrieved", []):
                C.out(f"  [{r['label']}] {r['chunk_id']}  relevance {r['dense']:.3f}  bm25 {r['lexical']:.2f}")
            continue
        t = time.time()
        res = rt.answer(q, history)
        last = res
        if args.json:
            out = {k: res[k] for k in ("answer", "citations", "cited_chunks", "refused", "tool_calls", "guard_events")}
            C.out(json.dumps(out, ensure_ascii=False, indent=1))
            continue
        tag = C.style(" [declined]", "yellow") if res["refused"] else ""
        C.out(C.style("agent>", "cyan", "bold") + tag + " " + res["answer"])
        for tc in res["tool_calls"]:
            C.out(C.style(f"   tool {tc['label']}: {tc['tool']}({json.dumps(tc['arguments'], ensure_ascii=False)})"
                          f" -> {tc['result'][:160]}", "grey"))
        for lab in res["citations"]:
            if lab.startswith("C"):
                r = next((x for x in res["retrieved"] if x["label"] == lab), None)
                if r:
                    ch = rt.index.by_id[r["chunk_id"]]
                    C.out(C.style(f"   [{lab}] {ch.header}", "grey"))
        C.out(C.style(f"   ({time.time() - t:.1f}s)", "grey"))
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": res["answer"]}]
    return 0


# -------------------------------------------------------------------- eval
def cmd_eval(args) -> int:
    from forgeai.factory.context import Run, make_gateway
    from forgeai.factory.evaluate import evaluate
    from forgeai.ingest import chunk_documents, load_folder
    from forgeai.retrieval.index import KnowledgeIndex
    from forgeai.runtime import definition as D
    from forgeai.util.io import read_json

    run_dir = Path(args.run)
    man = read_json(run_dir / "manifest.json")
    s = _restore_settings(man, args)
    defn = D.load(_resolve_agent(args.agent or str(run_dir)))
    s.agent_model = args.agent_model or defn["model"]["name"]
    defn["model"]["name"] = s.agent_model
    if args.judge_model:
        s.judge_model = args.judge_model
    C.info(f"agent {s.agent_model} | judge {s.judge_model}")
    cases = read_json(Path(args.cases) if args.cases else run_dir / "05_evalset.json")["cases"]
    tag = f"{s.agent_model}__judge-{s.judge_model}".replace(":", "-").replace("/", "-")
    out = run_dir / "eval_reruns" / f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{tag}"
    gw = make_gateway(s, out)
    run = Run(settings=s, run_dir=out, gw=gw, docs_dir=(run_dir / man["docs_dir"]).resolve())
    run.docs, run.skipped = load_folder(run.docs_dir)
    run.chunks = chunk_documents(run.docs)
    run.index = KnowledgeIndex.build(run.chunks, gw)
    res = evaluate(run, defn, cases, "re-eval", out)
    sc = res["scorecard"]
    C.ok(f"dev {sc['dev']['passed']}/{sc['dev']['n']}  holdout {sc['holdout']['passed']}/{sc['holdout']['n']}  "
         f"failures: {sc['failures'] or 'none'}  -> {out.as_posix()}")
    return 0


def _restore_settings(man: dict, args) -> Settings:
    st = man["settings"]
    s = Settings()
    for k, v in st.items():
        if hasattr(s, k) and k != "cache_dir":
            setattr(s, k, v)
    if getattr(args, "host", ""):
        s.host = args.host
    s.interactive = False
    s.approve_requirements = False
    return s.resolve()


# ------------------------------------------------------------------ replay
def cmd_replay(args) -> int:
    from forgeai.factory.pipeline import build
    from forgeai.util.io import read_json, write_json

    src = Path(args.run)
    man = read_json(src / "manifest.json")
    s = _restore_settings(man, args)
    s.replay = True
    dst = Path(args.out) if args.out else src.parent / f"{src.name}-replay"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    shutil.copy2(src / "llm_cache.sqlite", dst / "llm_cache.sqlite")
    if (src / "tool_record.json").exists():
        shutil.copy2(src / "tool_record.json", dst / "tool_record.json")
    req = read_json(src / "02_requirements.json")
    answers = [q["answer"] for q in req.get("interview", [])]
    write_json(dst / "_answers.json", answers)
    brief = (src / "brief.md").read_text(encoding="utf-8")
    started = _dt.datetime.fromisoformat(man["started"]) if man.get("started") else None
    build(s, brief, (src / man["docs_dir"]).resolve(), run_dir=dst, answers_file=dst / "_answers.json", now=started)
    new = read_json(dst / "manifest.json")["artifact_sha256"]
    old = man["artifact_sha256"]
    keys = sorted(k for k in old if k not in ("manifest.json",) and not k.startswith("eval_reruns"))
    same = [k for k in keys if new.get(k) == old[k]]
    diff = [k for k in keys if new.get(k) != old[k]]
    C.out()
    C.ok(f"replay reproduced {len(same)}/{len(keys)} artifacts byte-for-byte without calling a model")
    for k in diff:
        C.warn(f"differs: {k}")
    return 0 if not [d for d in diff if not d.endswith(("trace.jsonl",))] else 1


# ----------------------------------------------------------------- regress
def cmd_regress(args) -> int:
    from forgeai.factory.regress import regress

    return regress(Path(args.run), Path(args.docs), _restore_settings(
        __import__("forgeai.util.io", fromlist=["read_json"]).read_json(Path(args.run) / "manifest.json"), args))


# ------------------------------------------------------------------ doctor
def cmd_doctor(args) -> int:
    from forgeai.factory.context import make_backend
    from forgeai.llm.backends import BackendError

    s = _settings_from(args)
    ok = True
    C.out(C.style(f"ForgeAI {__version__} doctor", "bold"))
    py = sys.version_info
    (C.ok if py >= (3, 10) else C.fail)(f"Python {py.major}.{py.minor}.{py.micro} ({sys.platform})")
    ok &= py >= (3, 10)
    for mod in ("numpy", "pypdf"):
        try:
            __import__(mod)
            C.ok(f"{mod} installed")
        except ImportError:
            C.fail(f"{mod} missing: pip install {mod}")
            ok = False
    C.ok(f"console encoding {sys.stdout.encoding}; colour {'on' if C.COLOR else 'off'}")
    be = make_backend(s)
    try:
        C.ok(f"{s.backend} reachable at {s.host} (version {be.version()})")
        have = be.list_models()
    except BackendError as e:
        C.fail(f"{s.backend} not reachable: {e}")
        C.info("install Ollama from https://ollama.com and start it (Windows: it runs as a tray app)")
        return 1
    names = {m.split(":latest")[0] for m in have} | set(have)
    for role in ("factory_model", "agent_model", "judge_model", "embed_model"):
        m = getattr(s, role)
        present = m in names or f"{m}:latest" in have
        (C.ok if present else C.fail)(f"{role:<14} {m}" + ("" if present else f"   ->  ollama pull {m}"))
        ok &= present
    if ok:
        from forgeai.factory.context import make_gateway
        gw = make_gateway(s, None)
        gw.cache = None
        t = time.time()
        out = gw.chat_json("agent", [{"role": "user", "content": "Return JSON {\"ok\": true, \"word\": \"forge\"}"}],
                           {"type": "object", "properties": {"ok": {"type": "boolean"}, "word": {"type": "string"}},
                            "required": ["ok", "word"]}, stage="doctor")
        dt = time.time() - t
        C.ok(f"structured output from {s.agent_model}: {out}  ({dt:.1f}s)")
        t = time.time()
        gw.embed(["hello world"])
        C.ok(f"embeddings from {s.embed_model} ({time.time() - t:.1f}s)")
        # can the server keep every model of this profile resident at once? (default limit is 3)
        if hasattr(be, "loaded_models"):
            from concurrent.futures import ThreadPoolExecutor
            chat_models = sorted({s.factory_model, s.agent_model, s.judge_model})

            def ping(m):
                try:
                    be.chat(m, [{"role": "user", "content": "Say OK."}], None, {"max_tokens": 4})
                    return True
                except BackendError:
                    return False

            with ThreadPoolExecutor(len(chat_models)) as ex:
                list(ex.map(ping, chat_models))
            loaded = {m.split(":latest")[0] for m in be.loaded_models()}
            need = set(chat_models) | {s.embed_model}
            missing_res = [m for m in need if m not in loaded and f"{m}:latest" not in be.loaded_models()]
            if missing_res:
                C.warn(f"{len(need)} models must stay loaded together but the server holds only "
                       f"{len(loaded)} ({', '.join(sorted(loaded))}). Set OLLAMA_MAX_LOADED_MODELS={len(need)} and restart "
                       f"Ollama (Windows: setx OLLAMA_MAX_LOADED_MODELS {len(need)}), or use a profile with fewer models.")
            else:
                C.ok(f"all {len(need)} models resident together: {', '.join(sorted(need))}")
        # warm speed test (models are loaded now): a ~120-token generation
        t = time.time()
        r = be.chat(s.agent_model, [{"role": "user", "content": "List twelve colours, one per line, no other text."}],
                    None, {"max_tokens": 120, "temperature": 0.0})
        tps = r.tokens_out / max(0.01, time.time() - t)
        C.info(f"~{tps:.0f} output tokens/s for {s.agent_model} on this machine. "
               + ("Profile 'standard' is fine." if tps > 25 else "Slow machine: use --profile laptop or tiny, "
                  "and --max-minutes to bound the run."))
    return 0 if ok else 1


def cmd_ui(args) -> int:
    from forgeai.studio.server import serve

    serve(_settings_from(args), Path(args.root), port=args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forge", description="ForgeAI - the agent that builds agents.")
    ap.add_argument("--version", action="version", version=f"forgeai {__version__}")
    ap.add_argument("--quiet", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="run the factory end to end")
    b.add_argument("--brief", default="")
    b.add_argument("--brief-file", default="")
    b.add_argument("--docs", required=True)
    b.add_argument("--out", default="runs")
    b.add_argument("--name", default=None)
    b.add_argument("--answers", default="", help="JSON list/dict of interview answers (non-interactive)")
    b.add_argument("--force", action="store_true", help="build even if the brief is barely groundable")
    b.add_argument("--resume", default="", help="re-use an interrupted run folder (cached calls are free)")
    _common(b)
    b.set_defaults(fn=cmd_build)

    c = sub.add_parser("chat", help="chat with a produced agent")
    c.add_argument("target", help="run folder or agent.json")
    c.add_argument("--question", "-q", default="")
    c.add_argument("--json", action="store_true")
    _common(c)
    c.set_defaults(fn=cmd_chat)

    e = sub.add_parser("eval", help="re-run an eval set against an agent")
    e.add_argument("run")
    e.add_argument("--cases", default="")
    e.add_argument("--agent", default="")
    _common(e)
    e.set_defaults(fn=cmd_eval)

    r = sub.add_parser("replay", help="re-execute a run from its cache (no model needed)")
    r.add_argument("run")
    r.add_argument("--out", default="")
    _common(r)
    r.set_defaults(fn=cmd_replay)

    g = sub.add_parser("regress", help="documents changed: rebuild and re-run the old eval set")
    g.add_argument("run")
    g.add_argument("--docs", required=True)
    _common(g)
    g.set_defaults(fn=cmd_regress)

    d = sub.add_parser("doctor", help="check the environment")
    _common(d)
    d.set_defaults(fn=cmd_doctor)

    u = sub.add_parser("ui", help="ForgeAI Studio: build, inspect, chat and explain in the browser")
    u.add_argument("--port", type=int, default=7860)
    u.add_argument("--root", default=".", help="project folder holding runs/ and demos/")
    u.add_argument("--no-browser", action="store_true")
    _common(u)
    u.set_defaults(fn=cmd_ui)

    args = ap.parse_args(argv)
    C.set_quiet(args.quiet)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        C.out()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
