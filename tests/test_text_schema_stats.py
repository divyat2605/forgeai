from forgeai.llm.schema import coerce, extract_json, validate, obj, arr, NESTR, BOOL
from forgeai.util.stats import mcnemar_exact, paired_flips, wilson
from forgeai.util.text import (best_span, fact_match, looks_like_refusal, numbers_in, quote_in,
                               split_sentences)


def test_numbers_are_canonical():
    assert numbers_in("INR 1,200.50, ten days and 18%") == {"1200.5", "10", "18"}
    assert numbers_in("24 days") == {"24"}


def test_fact_match_requires_numbers():
    assert fact_match("24 days of annual leave", "You get 24 days of annual leave.")[0] == "match"
    assert fact_match("24 days of annual leave", "You get 25 days of annual leave.")[0] == "miss"
    assert fact_match("receipts above INR 500", "Receipts are needed for items over INR 500")[0] == "match"


def test_fact_match_partial_goes_to_judge():
    v, _ = fact_match("the line manager approves", "approval sits with your manager")
    assert v in ("partial", "miss")


def test_quote_verification_rejects_invented_quotes():
    text = "Claims must be submitted within 30 days of returning from travel."
    assert quote_in("submitted within 30 days of returning", text)
    assert quote_in("Claims must be  submitted within 30 days", text)
    assert not quote_in("submitted within 60 days", text)
    assert not quote_in("", text)


def test_best_span_repairs_paraphrase_to_verbatim():
    src = "All permanent employees are entitled to 24 days of paid annual leave per calendar year."
    span = best_span("employees get 24 days paid leave", src)
    assert span and span in src and "24" in span
    assert best_span("cost is 45 dollars", "The unit price is USD 54 per piece.") is None


def test_sentences_and_refusals():
    assert len(split_sentences("First fact. Second fact! Third?")) == 3
    assert looks_like_refusal("I'm sorry, that is not covered in the documents.")
    assert not looks_like_refusal("You get 24 days of annual leave.")


def test_schema_validate_and_coerce():
    s = obj({"name": NESTR, "ok": BOOL, "items": arr(NESTR, 1, 2)})
    assert validate({"name": "a", "ok": True, "items": ["x"]}, s) == []
    errs = validate({"name": "", "ok": "yes", "items": []}, s)
    assert len(errs) == 3
    fixed = coerce({"name": "a", "ok": "true", "items": ["x", "y", "z"], "extra": 1}, s)
    assert validate(fixed, s) == [] and fixed["ok"] is True and len(fixed["items"]) == 2


def test_extract_json_from_chatter():
    assert extract_json('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}
    assert extract_json('<think>hmm</think>{"a": {"b": "}"}}') == {"a": {"b": "}"}}


def test_wilson_and_mcnemar():
    lo, hi = wilson(16, 20)
    assert 0.55 < lo < 0.62 and 0.9 < hi < 0.95
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 6) < 0.05
    f = paired_flips({"a": False, "b": True, "c": True}, {"a": True, "b": False, "c": True})
    assert f["fixed"] == ["a"] and f["broke"] == ["b"] and f["net"] == 0
