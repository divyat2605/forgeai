"""End-to-end factory run with a scripted fake model: no Ollama, no network.

Exercises every stage, checks every artifact exists, the agent loads in the
generic runner, the weather tool is NOT attached to an HR agent, the gap topic
is flagged, the report is honest about failures, and a replay reproduces the
run from cache.
"""

import json
import re
from pathlib import Path

import pytest

from forgeai.config import Settings
from forgeai.factory.pipeline import build
from forgeai.llm.backends import ScriptedBackend
from forgeai.runtime.agent import AgentRuntime
from forgeai.util.io import read_json

LEAVE = """# Annual Leave
Permanent staff receive 24 days of annual leave per calendar year, accrued at 2 days per month.

# Sick Leave
Employees get 12 days of paid sick leave per year. A medical certificate is required for more than 2 consecutive days.

# Applying for Leave
Leave longer than 3 days must be applied for at least 14 days in advance in the KestrelHR portal.
"""
TRAVEL = """# Daily Allowance
The daily allowance is INR 1,200 per day for domestic travel and USD 60 per day for international travel.

# Expense Claims
Expense claims must be submitted within 30 days of returning. Receipts are required for items above INR 500.
"""


def _user(msgs):
    return next(m["content"] for m in reversed(msgs) if m["role"] == "user")


def _between(text, start, end):
    m = re.search(re.escape(start) + r"(.*?)" + (re.escape(end) if end else r"$"), text, re.S)
    return m.group(1).strip() if m else ""


def handler(pid, msgs, schema):
    u = _user(msgs)
    if pid == "intake.profile_doc":
        return {"summary": "HR policy document.", "topics": ["annual leave", "sick leave", "expenses"]}
    if pid in ("intake.draft", "intake.finalize"):
        return {"agent_name": "Kestrel HR Helper", "summary": "Answers HR policy questions for shore staff.",
                "audience": "office staff", "tone": "friendly, concise", "scope": "HR policies",
                "must_answer": [{"topic": "annual leave", "description": "days and accrual"},
                                {"topic": "sick leave", "description": "days and certificates"},
                                {"topic": "travel expense claims", "description": "allowances and claim deadlines"},
                                {"topic": "health insurance claims", "description": "insurance claim process"}],
                "must_refuse": [{"topic": "tax advice", "reason": "not HR policy"}],
                "out_of_scope_message": "Sorry, I can only help with Kestrel HR policies.",
                "assumptions": []}
    if pid == "intake.questions":
        return {"questions": [{"question": "Who are the users?", "why": "audience", "default_answer": "office staff"}]}
    if pid == "ground.topic":
        topic = _between(u, "REQUIRED TOPIC:", "DESCRIPTION:")
        if "insurance" in topic:
            return {"verdict": "unsupported", "evidence_quotes": [], "tool": "", "missing": "no insurance policy"}
        passages = _between(u, "PASSAGES RETRIEVED FROM THE DOCUMENTS:", "TOOLS THAT")
        first = re.search(r"\] (.{20,80}?)[.\n]", passages)
        return {"verdict": "supported", "evidence_quotes": [first.group(1)] if first else [], "tool": "", "missing": ""}
    if pid == "gen.tools":
        return {"decisions": [{"tool": "weather", "attach": True, "serves_topic": "annual leave", "reason": "why not"},
                              {"tool": "calculator", "attach": False, "serves_topic": "", "reason": "not needed"}]}
    if pid == "gen.system_prompt":
        return {k: f"{k} rules." for k in ("role", "audience_tone", "scope", "grounding", "refusal", "tools", "format")}
    if pid == "evalgen.answerable":
        passage = _between(u, '"""', '"""')
        sent = re.split(r"(?<=\.)\s", passage)[0]
        nums = re.findall(r"\d[\d,]*", sent)
        fact = " ".join(sent.split()[:6])
        return {"question": f"How many days or what amount applies to {' '.join(sent.split()[2:5])} ({nums[0] if nums else 'x'})?",
                "answer": sent, "answer_span": fact}
    if pid == "evalgen.multidoc":
        a = _between(u, "PASSAGE A", "PASSAGE B")
        b = _between(u, "PASSAGE B", "Write one")
        fa = " ".join(re.sub(r"^.*?\"\"\"", "", a, flags=re.S).split()[:4])
        fb = " ".join(re.sub(r"^.*?\"\"\"", "", b, flags=re.S).split()[:4])
        return {"question": "How do leave and expenses combine?", "answer": "both", "fact_a": fa, "fact_b": fb}
    if pid == "evalgen.application":
        return {"applicable": False, "question": "", "answer_span": "", "trap_span": "", "condition": ""}
    if pid == "evalgen.rephrase":
        return {"question": "hey quick q " + _between(u, "ORIGINAL QUESTION:", "Rewrite").lower()[:60]}
    if pid == "evalgen.out_of_scope":
        return {"questions": [{"question": f"What is the capital of country number {i}?", "why_refuse": "general"}
                              for i in range(8)] + [{"question": "Can you give me tax advice?", "why_refuse": "tax advice"}]}
    if pid in ("evalgen.verify_oos", "evalgen.verify_gap"):
        return {"answerable": False, "quote": ""}
    if pid == "evalgen.closed_book":
        return "unknown"
    if pid == "agent.answer":
        sources = _between(u, "SOURCES (cite by label):", "QUESTION:")
        q = u.split("QUESTION:")[-1]
        if "capital" in q or "tax" in q:
            return {"answer": "Sorry, I can only help with Kestrel HR policies.", "citations": [], "refused": True}
        m = re.search(r"\[(C\d+)\][^\n]*\n([^\n]+)", sources)
        if not m:
            return {"answer": "Sorry, I can only help with Kestrel HR policies.", "citations": [], "refused": True}
        return {"answer": m.group(2), "citations": [m.group(1)], "refused": False}
    if pid == "judge.fact":
        return {"stated": False, "quote": ""}
    if pid == "judge.claims":
        ids = re.findall(r"^(S\d+):", _between(u, "CLAIMS:", ""), re.M)
        return {"verdicts": [{"id": i, "supported": True, "quote": ""} for i in ids]}
    if pid == "critic.patch":
        return {"diagnosis": "too terse", "new_text": "Use only the SOURCES. Quote exact numbers. Cite labels.",
                "change_summary": "tightened grounding rules"}
    if pid == "agent.query_rewrite":
        return {"query": "leave policy days"}
    raise AssertionError(f"unscripted prompt {pid}")


@pytest.fixture()
def docs(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    (d / "leave_policy.md").write_text(LEAVE, encoding="utf-8")
    (d / "travel_policy.md").write_text(TRAVEL, encoding="utf-8")
    return d


def _settings(tmp_path: Path, **kw) -> Settings:
    s = Settings(profile="laptop", workers=2, interactive=False, eval_target=20, cache_dir=tmp_path / "cache", **kw)
    s.judge_model = "gemma3:4b"
    return s


def test_full_factory_run_offline(tmp_path, docs):
    be = ScriptedBackend(handler)
    run_dir = build(_settings(tmp_path), "Answer HR policy questions incl. health insurance claims.", docs,
                    out_root=tmp_path / "runs", name="t", backend=be)
    for f in ("manifest.json", "01_corpus.json", "02_requirements.json", "02_requirements.md", "03_groundability.json",
              "04_tool_decisions.json", "05_evalset.json", "07_iterations.json", "08_judge_canaries.json",
              "REPORT.md", "report.json", "agent/agent.json", "agent/knowledge/chunks.json", "trace.jsonl",
              "llm_cache.sqlite", "06_iterations/iter_0/scorecard.json"):
        assert (run_dir / f).exists(), f
    g = read_json(run_dir / "03_groundability.json")
    assert [x["topic"] for x in g["gaps"]] == ["health insurance claims"]
    tools = read_json(run_dir / "04_tool_decisions.json")
    weather = next(t for t in tools if t["tool"] == "weather")
    assert weather["model_said"] and not weather["attach"]        # HR agent + weather = vetoed
    ev = read_json(run_dir / "05_evalset.json")
    assert ev["stats"]["dev"] and ev["stats"]["holdout"]
    assert any(c["kind"] in ("out_of_scope", "must_refuse") for c in ev["cases"])
    report = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "Holdout" in report and "What still fails" in report and "health insurance claims" in report
    man = read_json(run_dir / "manifest.json")
    assert man["status"] == "complete" and "\\" not in json.dumps(man["artifact_sha256"])
    # the generic runner loads the produced definition
    from forgeai.factory.context import make_gateway
    gw = make_gateway(_settings(tmp_path).resolve(), None, backend=be)
    rt = AgentRuntime.from_path(run_dir / "agent" / "agent.json", gw)
    res = rt.answer("How many days of annual leave do I get?")
    assert not res["refused"] and res["citations"]
    assert rt.answer("What is the capital of country number 3?")["refused"]


def test_replay_needs_no_model(tmp_path, docs):
    be = ScriptedBackend(handler)
    run_dir = build(_settings(tmp_path), "Answer HR policy questions.", docs, out_root=tmp_path / "runs", name="r",
                    backend=be)

    def boom(*a, **k):
        raise AssertionError("replay must not call the model")

    s = _settings(tmp_path, replay=True)
    dst = tmp_path / "replay"
    dst.mkdir()
    import shutil
    shutil.copy2(run_dir / "llm_cache.sqlite", dst / "llm_cache.sqlite")
    man = read_json(run_dir / "manifest.json")
    import datetime as dt
    build(s, "Answer HR policy questions.", docs, run_dir=dst, backend=ScriptedBackend(boom),
          now=dt.datetime.fromisoformat(man["started"]))
    a = read_json(run_dir / "05_evalset.json")
    b = read_json(dst / "05_evalset.json")
    assert a == b
    assert (run_dir / "REPORT.md").read_text(encoding="utf-8").split("## Cost")[0] == \
        (dst / "REPORT.md").read_text(encoding="utf-8").split("## Cost")[0]


def test_ungroundable_brief_stops(tmp_path, docs):
    def h(pid, msgs, schema):
        if pid == "ground.topic":
            return {"verdict": "unsupported", "evidence_quotes": [], "tool": "", "missing": "nothing"}
        return handler(pid, msgs, schema)

    from forgeai.factory.pipeline import NotGroundable
    with pytest.raises(NotGroundable):
        build(_settings(tmp_path), "Explain quantum chromodynamics.", docs, out_root=tmp_path / "runs", name="u",
              backend=ScriptedBackend(h))
