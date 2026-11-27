"""Stage 1 - Intake interviewer.

Profiles every document, drafts requirements from the brief, asks the
requester at most five high-impact questions (each with a stated default so an
unattended run still proceeds, and every defaulted answer is recorded as an
assumption), then writes the structured requirements document. Optional human
checkpoint: the requester approves or edits the requirements before anything
is generated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from forgeai.factory.context import Run
from forgeai.llm.gateway import LLMError
from forgeai.llm.schema import NESTR, STR, arr, obj
from forgeai.util import console as C
from forgeai.util.io import atomic_write_text, read_json, write_json
from forgeai.util.text import quote_in

TOPIC = obj({"topic": NESTR, "description": STR})
REFUSE = obj({"topic": NESTR, "reason": STR})
REQ_SCHEMA = obj({
    "agent_name": NESTR, "summary": NESTR, "audience": NESTR, "tone": NESTR, "scope": NESTR,
    "must_answer": arr(TOPIC, 1, 12), "must_refuse": arr(REFUSE, 1, 8),
    "out_of_scope_message": NESTR, "assumptions": arr(STR, 0, 12),
})
PROFILE_SCHEMA = obj({"summary": NESTR, "topics": arr(NESTR, 1, 8)})
Q_SCHEMA = obj({"questions": arr(obj({"question": NESTR, "why": STR, "default_answer": NESTR}), 0, 8)})


def profile_corpus(run: Run) -> None:
    def one(doc):
        if doc.table is not None:
            sample = "\n".join("; ".join(f"{k}: {v}" for k, v in r.items()) for r in doc.table.rows[:6])
            excerpt = f"Table with columns: {', '.join(doc.table.columns)}\n{len(doc.table.rows)} rows. Sample:\n{sample}"
        else:
            excerpt = doc.text[:2600]
        try:
            p = run.gw.run_prompt("factory", "intake.profile_doc", PROFILE_SCHEMA, stage="intake.profile",
                                  path=doc.path, headings=", ".join(doc.card()["headings"][:20]) or "(none)",
                                  excerpt=excerpt)
        except LLMError:
            p = {"summary": doc.title, "topics": [h for h in doc.card()["headings"][:6]] or [doc.title]}
        return doc.doc_id, p

    run.profiles = dict(run.pmap(one, run.docs, "profiling documents"))
    write_json(run.path("01_corpus.json"), {
        "documents": [{**d.card(), "profile": run.profiles.get(d.doc_id)} for d in run.docs],
        "skipped": run.skipped,
        "chunks": len(run.chunks),
    })


def _clean_requirements(req: dict) -> dict:
    def dedupe(items, key):
        seen, out = set(), []
        for it in items:
            k = it[key].strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append({**it, key: it[key].strip()})
        return out
    req["must_answer"] = dedupe(req.get("must_answer", []), "topic")[:10]
    req["must_refuse"] = dedupe(req.get("must_refuse", []), "topic")[:6]
    req["assumptions"] = [a for a in req.get("assumptions", []) if a.strip()]
    return req


NOTES_SCHEMA = obj({"answered": {"type": "boolean"}, "quote": STR})


def _ask(questions: list[dict], run: Run, answers_file: Path | None) -> list[dict]:
    """Answers come from (in order): an answers file (exact replay), the
    requester's notes (a model answers ONLY from them), the live requester on
    a terminal, else the question's stated default - and the source is recorded."""
    preset: dict = {}
    notes = ""
    if answers_file:
        if Path(answers_file).suffix.lower() in (".md", ".txt"):
            notes = Path(answers_file).read_text(encoding="utf-8")
        else:
            data = read_json(answers_file)
            if isinstance(data, list):
                preset = {i: a for i, a in enumerate(data)}
            elif isinstance(data, dict):
                preset = {i: data.get(q["question"], data.get(str(i + 1))) for i, q in enumerate(questions)}
    if notes:
        def by_notes(q):
            try:
                r = run.gw.run_prompt("factory", "intake.answer_from_notes", NOTES_SCHEMA, stage="intake.notes",
                                      notes=notes[:6000], question=q["question"])
                q_ = r["quote"].strip().strip('"')
                # the requester's own words only: the quote must exist verbatim in the notes
                return q_ if r["answered"] and q_ and quote_in(q_, notes) else None
            except LLMError:
                return None
        for i, a in enumerate(run.pmap(by_notes, questions)):
            if a:
                preset[i] = a
    qa = []
    interactive = run.settings.interactive and sys.stdin is not None and sys.stdin.isatty() and not (preset or notes)
    for i, q in enumerate(questions):
        ans, source = None, "default"
        if preset.get(i):
            ans, source = str(preset[i]), ("requester-notes" if notes else "answers-file")
        elif interactive:
            C.out(f"\n  {C.style(f'Q{i + 1}/{len(questions)}', 'bold')} {q['question']}")
            C.out(C.style(f"      (why: {q['why']})", "grey"))
            try:
                raw = input(f"      default: {q['default_answer']}\n      > ").strip()
            except EOFError:
                raw = ""
            if raw:
                ans, source = raw, "requester"
        if ans is None:
            ans = q["default_answer"]
        qa.append({**q, "answer": ans, "source": source})
    return qa


def requirements_markdown(req: dict, qa: list[dict] | None = None, ground: dict | None = None) -> str:
    L = [f"# Requirements - {req['agent_name']}", "", f"**Summary.** {req['summary']}", "",
         f"**Audience.** {req['audience']}  ", f"**Tone.** {req['tone']}  ", f"**Scope.** {req['scope']}", "",
         "## Must answer", ""]
    gt = {t["topic"]: t for t in (ground or {}).get("topics", [])}
    for t in req["must_answer"]:
        g = gt.get(t["topic"])
        badge = f" `{g['verdict']}`" if g else ""
        L.append(f"- **{t['topic']}**{badge} - {t.get('description', '')}")
    L += ["", "## Must refuse", ""]
    L += [f"- **{t['topic']}** - {t.get('reason', '')}" for t in req["must_refuse"]]
    L += ["", f"**Refusal message.** \"{req['out_of_scope_message']}\"", ""]
    if req.get("assumptions"):
        L += ["## Assumptions", ""] + [f"- {a}" for a in req["assumptions"]] + [""]
    if qa:
        L += ["## Interview", "", "| # | Question | Answer | Source |", "|---|---|---|---|"]
        for i, q in enumerate(qa, 1):
            L.append(f"| {i} | {q['question']} | {q['answer']} | {q['source']} |")
        L.append("")
    return "\n".join(L)


def checkpoint(run: Run, req: dict) -> dict:
    """Human checkpoint: approve, or edit requirements.json and reload."""
    path = run.path("02_requirements.json")
    write_json(path, req)
    if not (run.settings.approve_requirements and run.settings.interactive and sys.stdin.isatty()):
        return req
    C.out()
    C.out(C.style("  Human checkpoint - review the requirements before the agent is generated:", "bold"))
    C.out(f"    {path}")
    while True:
        try:
            ans = input("    [a]pprove / [e]dit (opens the file) / [r]eload after editing > ").strip().lower()
        except EOFError:
            ans = "a"
        if ans in ("", "a", "approve"):
            req["approved_by"] = "requester"
            return req
        if ans.startswith("e"):
            _open_in_editor(path)
        if ans.startswith(("e", "r")):
            try:
                new = read_json(path)
                from forgeai.llm.schema import validate
                errs = validate(new, REQ_SCHEMA)
                if errs:
                    C.warn("edited file is invalid: " + "; ".join(errs[:3]))
                    continue
                req = _clean_requirements(new)
                req["edited_by_requester"] = True
                C.ok("reloaded edited requirements")
            except (json.JSONDecodeError, OSError) as e:
                C.warn(f"could not read edited file: {e}")


def _open_in_editor(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            import subprocess
            editor = os.environ.get("EDITOR")
            if editor:
                subprocess.call([editor, str(path)])
            else:
                subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
    except Exception as e:  # noqa: BLE001
        C.warn(f"open the file manually: {path} ({e})")


def interview(run: Run, answers_file: Path | None = None) -> dict:
    corpus = run.corpus_card()
    draft = run.gw.run_prompt("factory", "intake.draft", REQ_SCHEMA, stage="intake.draft",
                              brief=run.brief, corpus=corpus)
    draft = _clean_requirements(draft)
    try:
        qs = run.gw.run_prompt("factory", "intake.questions", Q_SCHEMA, stage="intake.questions",
                               brief=run.brief, draft=json.dumps(draft, indent=1, ensure_ascii=False),
                               corpus=corpus, max_q=run.settings.max_questions)["questions"]
    except LLMError:
        qs = []
    qs = qs[: run.settings.max_questions]          # hard cap: at most 5 questions
    qa = _ask(qs, run, answers_file)
    if qa:
        qa_txt = "\n".join(f"- Q: {q['question']}\n  A: {q['answer']}{' (default)' if q['source'] == 'default' else ''}"
                           for q in qa)
        try:
            req = run.gw.run_prompt("factory", "intake.finalize", REQ_SCHEMA, stage="intake.finalize",
                                    brief=run.brief, draft=json.dumps(draft, indent=1, ensure_ascii=False), qa=qa_txt)
            req = _clean_requirements(req)
        except LLMError:
            req = draft
            req["assumptions"] = req.get("assumptions", []) + [f"{q['question']} -> {q['answer']}" for q in qa]
    else:
        req = draft
    req["interview"] = qa
    req = checkpoint(run, req)
    run.requirements = req
    write_json(run.path("02_requirements.json"), req)
    atomic_write_text(run.path("02_requirements.md"), requirements_markdown(req, qa))
    return req
