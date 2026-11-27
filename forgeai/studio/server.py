"""ForgeAI Studio - a zero-dependency web app for the factory (`forge ui`).

Standard library only (http.server), so it runs on any Windows/macOS/Linux
machine that runs ForgeAI. It serves a hand-built single-page front end and a
small JSON API over the run folders on disk:

  GET  /api/runs                      every run found under runs/, demos/*/run, bench/runs/
  GET  /api/run?id=ID                 one run's artifacts, bundled for the UI
  GET  /api/text?id=ID&path=REPORT.md a text artifact
  POST /api/build                     start a factory run (subprocess); returns a job id
  GET  /api/job?id=JOB&since=N        new log lines + parsed stage progress
  POST /api/chat                      ask a run's agent (same runtime as the evals)
  GET  /api/env                       models / backend summary

Everything the UI shows is read from artifacts at request time; nothing is
invented in the browser.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from forgeai import __version__
from forgeai.config import PROFILES, Settings

STATIC = Path(__file__).resolve().parent / "static"
STAGE_RE = re.compile(r"^\[(\d+(?:\.\w+)?)\]\s+(.*)$")


def _read(p: Path, default=None):
    try:
        if p.suffix == ".jsonl":
            return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        if p.suffix == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        return p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return default


class Studio:
    def __init__(self, root: Path, settings: Settings):
        self.root = Path(root).resolve()
        self.settings = settings
        self.jobs: dict[str, dict] = {}
        self.agents: dict[str, object] = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ runs
    def run_dirs(self) -> list[Path]:
        cands = []
        for pattern in ("runs/*", "demos/*/run", "bench/runs/*"):
            cands += [p for p in self.root.glob(pattern) if (p / "manifest.json").exists()]
        return sorted(set(cands), key=lambda p: p.stat().st_mtime, reverse=True)

    def rid(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    def path_of(self, rid: str) -> Path:
        p = (self.root / rid).resolve()
        if self.root not in p.parents or not (p / "manifest.json").exists():
            raise FileNotFoundError(rid)
        return p

    def summary(self, p: Path) -> dict:
        man = _read(p / "manifest.json", {}) or {}
        rep = _read(p / "report.json") or {}
        req = _read(p / "02_requirements.json") or {}
        g = _read(p / "03_groundability.json") or {}
        ev = (_read(p / "05_evalset.json") or {}).get("stats", {})
        return {
            "id": self.rid(p), "name": p.name if p.name != "run" else p.parent.name,
            "status": man.get("status"), "started": man.get("started"),
            "brief": (_read(p / "brief.md") or "").strip(),
            "agent": req.get("agent_name"), "holdout": rep.get("holdout"), "dev": rep.get("dev"),
            "baseline": rep.get("baseline"), "tools": rep.get("tools"), "gaps": [x["topic"] for x in g.get("gaps", [])],
            "coverage": g.get("coverage"), "cases": ev.get("total"),
            "judge": (rep.get("canaries") or {}).get("overall"),
            "minutes": round((man.get("meter") or {}).get("wall_seconds", 0) / 60, 1),
            "models": {k: (man.get("settings") or {}).get(k) for k in ("factory_model", "agent_model", "judge_model")},
        }

    def bundle(self, rid: str) -> dict:
        p = self.path_of(rid)
        verdicts = _read(p / "09_final_verdicts.jsonl", []) or []
        responses = {r.get("case_id"): r for r in (_read(p / "09_final_responses.jsonl", []) or [])}
        base_v = {v["id"]: v for v in (_read(p / "06_iterations" / "iter_0" / "verdicts.jsonl", []) or [])}
        ev = _read(p / "05_evalset.json") or {}
        cases = []
        vmap = {v["id"]: v for v in verdicts}
        for c in ev.get("cases", []):
            r = responses.get(c["id"], {})
            cases.append({**c, "verdict": vmap.get(c["id"]), "baseline_pass": (base_v.get(c["id"]) or {}).get("pass"),
                          "response": {k: r.get(k) for k in ("answer", "refused", "citations", "cited_chunks", "retrieved",
                                                              "tool_calls", "contexts", "guard_events", "latency_s",
                                                              "top_relevance")}})
        return {
            "summary": self.summary(p),
            "manifest": _read(p / "manifest.json"),
            "corpus": _read(p / "01_corpus.json"),
            "requirements": _read(p / "02_requirements.json"),
            "groundability": _read(p / "03_groundability.json"),
            "tools": _read(p / "04_tool_decisions.json"),
            "evalstats": ev.get("stats"),
            "cases": cases,
            "tournament": _read(p / "06_tournament" / "tournament.json"),
            "iterations": _read(p / "07_iterations.json"),
            "changes": _read(p / "07_changes.jsonl", []),
            "canaries": _read(p / "08_judge_canaries.json"),
            "report": _read(p / "report.json"),
            "agent": _read(p / "agent" / "agent.json"),
            "final": _read(p / "09_final_scorecard.json"),
        }

    # ----------------------------------------------------------------- build
    def start_build(self, body: dict) -> str:
        job = uuid.uuid4().hex[:10]
        work = Path(tempfile.mkdtemp(prefix="forge-studio-"))
        brief = (body.get("brief") or "").strip()
        if not brief:
            raise ValueError("a brief is required")
        (work / "brief.md").write_text(brief + "\n", encoding="utf-8")
        if body.get("files"):
            docs = work / "docs"
            docs.mkdir()
            for f in body["files"]:
                name = Path(f["name"]).name
                (docs / name).write_bytes(base64.b64decode(f["b64"]))
        else:
            docs = Path(body.get("docs_path") or "")
            if not docs.is_absolute():
                docs = self.root / docs
            if not docs.is_dir():
                raise ValueError(f"documents folder not found: {docs}")
        cmd = [sys.executable, "-m", "forgeai", "build", "--brief-file", str(work / "brief.md"), "--docs", str(docs),
               "--out", str(self.root / "runs"), "--profile", body.get("profile") or self.settings.profile,
               "--unattended"]
        if (body.get("notes") or "").strip():
            (work / "requester_notes.md").write_text(body["notes"], encoding="utf-8")
            cmd += ["--answers", str(work / "requester_notes.md")]
        if body.get("max_minutes"):
            cmd += ["--max-minutes", str(float(body["max_minutes"]))]
        if body.get("name"):
            cmd += ["--name", re.sub(r"[^a-zA-Z0-9_-]+", "-", body["name"])[:40]]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(cmd, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
        state = {"id": job, "lines": [], "stages": [], "status": "running", "run": None, "t0": time.time(),
                 "proc": proc}
        self.jobs[job] = state

        def pump():
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\n")
                with self.lock:
                    state["lines"].append(line)
                    m = STAGE_RE.match(line.strip())
                    if m:
                        state["stages"].append({"n": m.group(1), "title": m.group(2), "t": round(time.time() - state["t0"], 1)})
                    rm = re.search(r"run (\S*runs[/\\]\S+)", line)
                    if rm and not state["run"]:
                        state["run"] = rm.group(1)
            rc = proc.wait()
            with self.lock:
                state["status"] = "done" if rc == 0 else ("stopped" if rc == 3 else f"failed ({rc})")
                if state["run"]:
                    try:
                        state["run_id"] = self.rid(Path(state["run"]) if Path(state["run"]).is_absolute()
                                                  else self.root / state["run"])
                    except ValueError:
                        state["run_id"] = None

        threading.Thread(target=pump, daemon=True).start()
        return job

    def job(self, jid: str, since: int) -> dict:
        st = self.jobs[jid]
        with self.lock:
            return {"status": st["status"], "lines": st["lines"][since:], "next": len(st["lines"]),
                    "stages": st["stages"], "run_id": st.get("run_id"), "elapsed": round(time.time() - st["t0"], 1)}

    # ------------------------------------------------------------------ chat
    def chat(self, body: dict) -> dict:
        from forgeai.factory.context import make_gateway
        from forgeai.runtime.agent import AgentRuntime

        rid = body["run"]
        p = self.path_of(rid)
        with self.lock:
            rt = self.agents.get(rid)
        if rt is None:
            defn = _read(p / "agent" / "agent.json")
            s = Settings(backend=self.settings.backend, host=self.settings.host, agent_model=defn["model"]["name"],
                         embed_model=defn["knowledge"].get("embed_model", "")).resolve()
            rt = AgentRuntime.from_path(p / "agent" / "agent.json", make_gateway(s, None))
            with self.lock:
                self.agents[rid] = rt
        res = rt.answer(body["message"], body.get("history") or [])  # type: ignore[attr-defined]
        passages = {}
        for r in res["retrieved"]:
            ch = rt.index.by_id[r["chunk_id"]]  # type: ignore[attr-defined]
            passages[r["label"]] = {"chunk_id": ch.chunk_id, "header": ch.header, "text": ch.text,
                                    "dense": r["dense"], "lexical": r["lexical"]}
        return {**{k: res[k] for k in ("answer", "refused", "citations", "tool_calls", "guard_events", "latency_s",
                                       "top_relevance")}, "passages": passages}


def make_handler(studio: Studio):
    class H(BaseHTTPRequestHandler):
        server_version = f"ForgeAIStudio/{__version__}"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/runs":
                    return self._json([studio.summary(p) for p in studio.run_dirs()])
                if u.path == "/api/run":
                    return self._json(studio.bundle(q["id"]))
                if u.path == "/api/text":
                    p = studio.path_of(q["id"]) / q["path"]
                    return self._json({"text": _read(p, "")})
                if u.path == "/api/job":
                    return self._json(studio.job(q["id"], int(q.get("since", 0))))
                if u.path == "/api/brief":
                    briefs = sorted(studio.root.glob("docs/*.brief")) + sorted(studio.root.glob("*.brief"))
                    if not briefs:
                        return self._json({"error": "no .brief deck found in docs/"}, 404)
                    b = briefs[0]
                    return self._json({"path": b.relative_to(studio.root).as_posix(), "text": b.read_text(encoding="utf-8")})
                if u.path == "/api/asset":
                    f = (studio.root / q["path"]).resolve()
                    if studio.root not in f.parents or not f.is_file() or f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"):
                        return self._json({"error": "not found"}, 404)
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                if u.path == "/api/env":
                    s = studio.settings
                    return self._json({"version": __version__, "profile": s.profile, "profiles": PROFILES,
                                       "backend": s.backend, "host": s.host, "root": studio.root.as_posix()})
            except (FileNotFoundError, KeyError) as e:
                return self._json({"error": f"not found: {e}"}, 404)
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            f = (STATIC / path).resolve()
            if STATIC not in f.parents or not f.is_file():
                f = STATIC / "index.html"
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, f.read_bytes(), ctype)

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if self.path == "/api/build":
                    return self._json({"job": studio.start_build(body)})
                if self.path == "/api/chat":
                    return self._json(studio.chat(body))
            except (ValueError, KeyError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{e.__class__.__name__}: {e}"}, 500)
            self._json({"error": "unknown endpoint"}, 404)

    return H


def serve(settings: Settings, root: Path = Path("."), port: int = 7860, open_browser: bool = True) -> None:
    studio = Studio(root, settings)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(studio))
    url = f"http://127.0.0.1:{port}/"
    print(f"ForgeAI Studio {__version__}  {url}   (root {studio.root.as_posix()}; Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
