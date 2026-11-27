"""The checks that stop the factory from lying to itself."""

from forgeai.factory.evalgen import _informative, _vague, _verify_facts
from forgeai.factory.generator import refusal_message, select_tools  # noqa: F401
from forgeai.factory.judge import Judge, _derivable
from forgeai.factory.optimizer import _threshold_patch
from forgeai.util.text import fact_match, quote_in


def test_vague_questions_are_rejected():
    assert _vague("What is the purpose of this policy?")
    assert _vague("What is the main focus of the guidelines for remote work?")
    assert not _vague("How many days of annual leave do new joiners get?")


def test_uninformative_facts_are_rejected():
    assert _informative("All shore staff must adhere strictly to the provisions", "What are the rules?", "x") \
        == "boilerplate fact"
    assert _informative("Claims after this deadline will not be processed", "What is the deadline for claims?",
                        "within 30 days") is not None
    assert _informative("within 30 days of returning", "What is the deadline for claims?", "within 30 days") is None


def test_fact_verification_repairs_or_drops():
    passage = "Expense claims must be submitted in the portal within 30 days of returning from the trip."
    kept, notes = _verify_facts(["claims submitted within 30 days of returning"], passage, "When are claims due?")
    assert kept and kept[0] in passage
    kept, _ = _verify_facts(["within 45 days"], passage, "When are claims due?")
    assert kept == []


def test_refusal_message_never_advertises_a_gap():
    req = {"out_of_scope_message": "I help with leave, travel and health insurance claims.",
           "must_answer": [{"topic": "Leave"}, {"topic": "Travel"}, {"topic": "Health insurance claims"}]}
    g = {"gaps": [{"topic": "Health insurance claims"}]}
    msg = refusal_message(req, g)
    assert "insurance" not in msg.lower() and "leave" in msg.lower()
    assert refusal_message({**req, "out_of_scope_message": "Sorry, HR policies only."}, g) == "Sorry, HR policies only."


def test_stemming_and_number_strictness():
    assert fact_match("must be submitted every year by 30 April",
                      "Submit it by 30 April each year.")[0] == "match"
    assert fact_match("within 30 days", "within 31 days")[0] == "miss"
    assert not quote_in("refund within 60 days", "Refunds are issued within 30 days of purchase.")


def test_derivable_numbers_are_not_hallucinations():
    assert _derivable("4986", {"12", "415.5"})          # 12 x 415.5
    assert not _derivable("7345", {"12", "415.5"})


class _NoLLM:
    def run_prompt(self, *a, **k):
        raise AssertionError("deterministic path expected")


def test_judge_deterministic_paths():
    j = Judge(_NoLLM())
    case = {"id": "E1", "kind": "answerable", "split": "dev", "question": "How many days of annual leave?",
            "expected": {"should_refuse": False, "key_facts": [{"text": "24 days of annual leave"}], "gold_chunks": []}}
    ok = {"answer": "You get 24 days of annual leave per year.", "refused": False, "citations": ["C1"],
          "contexts": {"C1": "Staff get 24 days of annual leave per calendar year."}, "retrieved": [], "tool_calls": []}
    v = j.judge(case, ok)
    assert v["pass"] and v["grounded"] and v["gold_retrieved"]
    bad = {**ok, "answer": "You get 30 days of annual leave per year."}
    v = j.judge(case, bad)
    assert not v["pass"] and v["failure"]["category"] == "hallucination"
    miss = {**ok, "refused": True, "answer": "Sorry.", "contexts": {"C1": "Unrelated travel text."}}
    assert j.judge(case, miss)["failure"]["category"] == "retrieval_miss"
    wrong = {**ok, "refused": True, "answer": "Sorry."}
    assert j.judge(case, wrong)["failure"]["category"] == "wrong_refusal"
    oos = {"id": "E2", "kind": "out_of_scope", "split": "dev", "question": "Capital of France?",
           "expected": {"should_refuse": True, "key_facts": []}}
    assert j.judge(oos, {**ok, "refused": True})["pass"]


def test_abstention_threshold_is_calibrated_on_dev_only():
    defn = {"tools": [], "guards": {"min_relevance": 0.0}}
    verdicts = [{"id": "a", "should_refuse": False, "refused": False}, {"id": "b", "should_refuse": False, "refused": False},
                {"id": "o", "should_refuse": True, "refused": False}]
    resp = {"a": {"top_relevance": 0.71}, "b": {"top_relevance": 0.66}, "o": {"top_relevance": 0.41}}
    p = _threshold_patch(defn, verdicts, resp)
    assert p and 0.41 < p["after"] < 0.66
    resp["o"]["top_relevance"] = 0.69                   # not separable -> no patch
    assert _threshold_patch(defn, verdicts, resp) is None


def test_rule_misapplication_is_named():
    j = Judge(_NoLLM())
    case = {"id": "E3", "kind": "application", "split": "dev", "question": "3 nights in Pune - hotel limit?",
            "expected": {"should_refuse": False, "key_facts": [{"text": "INR 4,000 in all other cities"}],
                         "trap": "INR 6,500 in metro cities", "gold_chunks": []}}
    ctx = {"C1": "Hotel limits per night: INR 6,500 in metro cities (Mumbai, Delhi); INR 4,000 in all other cities."}
    res = {"answer": "The limit is INR 6,500 in metro cities per night.", "refused": False, "citations": ["C1"],
           "contexts": ctx, "retrieved": [], "tool_calls": []}
    v = j.judge(case, res)
    assert not v["pass"] and v["failure"]["subtype"] == "rule_misapplied"
    ok = {**res, "answer": "Pune is not a metro city, so the limit is INR 4,000 in all other cities per night."}
    assert j.judge(case, ok)["pass"]


def test_live_data_topics_are_tool_backed_not_gaps():
    import re
    from forgeai.runtime.tools import REGISTRY
    assert re.search(REGISTRY["weather"].live_need, "weather outlook at the delivery port")
    assert not re.search(REGISTRY["current_date"].live_need, "allowances and claim deadlines")
