"""Deterministic text checks: normalisation, numbers, fact and quote matching.

These are the parts of the judge and the eval generator that must NOT depend on
a language model. A small model can be wrong; these functions cannot be
persuaded. Wherever ForgeAI asks a model to "quote" something, the quote is
re-verified here before it is believed.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
    "…": "...",
})

STOPWORDS = frozenset("""
a an the and or but if then else of to in on at by for with from into onto over under
is are was were be been being am do does did done have has had having can could may might
must shall should will would this that these those it its it's as about above after again
against all any because before below between both during each few further here how i me my
myself more most no nor not only other our ours ourselves out own same she he him his her
hers so some such than too very s t just don now what which who whom why where when there
their theirs them themselves they you your yours yourself we us also per via upon within
every each
""".split())

_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_NUM_RE = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?(?![\w])|(?<![\w.])-?\d+(?:\.\d+)?")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def normalize(text: str) -> str:
    """Lower-case, unify unicode punctuation, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text or "").translate(_TRANS).lower()
    return re.sub(r"\s+", " ", t).strip()


def _canon_number(raw: str) -> str:
    s = raw.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return s
    if v == int(v):
        return str(int(v))
    return ("%.6f" % v).rstrip("0").rstrip(".")


def numbers_in(text: str) -> set[str]:
    """All numbers in text, canonicalised (1,200.50 -> 1200.5; 'ten' -> 10)."""
    t = normalize(text)
    found = {_canon_number(m.group(0)) for m in _NUM_RE.finditer(t)}
    for w in re.findall(r"[a-z]+", t):
        if w in _WORD_NUM:
            found.add(str(_WORD_NUM[w]))
    return found


def _stem(tok: str) -> str:
    for suf in ("ings", "ing", "edly", "ies", "ied", "ed", "es", "ly", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            stem = tok[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
            # submitted -> submitt -> submit ; planning -> plann -> plan
            if suf in ("ed", "ing", "ings", "edly") and len(stem) > 3 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
                stem = stem[:-1]
            return stem
    return tok


def tokens(text: str, content_only: bool = False) -> list[str]:
    toks = _TOKEN_RE.findall(normalize(text))
    if content_only:
        toks = [t for t in toks if t not in STOPWORDS]
    return [_stem(t) for t in toks]


def content_tokens(text: str) -> list[str]:
    return tokens(text, content_only=True)


def fact_match(fact: str, text: str) -> tuple[str, float]:
    """Is `fact` stated in `text`?  Returns (verdict, score).

    verdict: "match"   - fact is present (substring, or all numbers + >=80% content words)
             "partial" - some evidence, worth asking the model judge
             "miss"    - clearly absent (e.g. a required number is missing)
    Deliberately conservative toward "partial": the LLM judge then decides, and
    its answer must come with a verified quote.
    """
    nf, nt = normalize(fact), normalize(text)
    if not nf:
        return "match", 1.0
    if nf in nt:
        return "match", 1.0
    fnums = numbers_in(fact)
    if fnums and not fnums.issubset(numbers_in(text)):
        return "miss", 0.0
    ftoks = set(content_tokens(fact))
    if not ftoks:
        return ("match", 1.0) if fnums else ("partial", 0.5)
    ttoks = set(content_tokens(text))
    recall = len(ftoks & ttoks) / len(ftoks)
    if recall >= 0.8 and (len(ftoks) >= 2 or fnums):
        return "match", recall
    if recall >= 0.34 or (fnums and recall > 0):
        return "partial", recall
    # No number is at stake: a paraphrase ("cannot work remotely" for "must work from the office")
    # can share almost no words with the fact, so only the model judge may call it a miss.
    if not fnums and len(ftoks) >= 3:
        return "partial", recall
    return "miss", recall


def quote_in(quote: str, text: str, threshold: float = 0.88) -> bool:
    """Verify that a model-supplied quote really occurs in text (tolerant to
    whitespace/punctuation/case, and to tiny OCR-style differences)."""
    q, t = normalize(quote), normalize(text)
    if not q:
        return False
    if q in t:
        return True
    # fuzzy matching must never forgive a changed number
    if not numbers_in(quote).issubset(numbers_in(text)):
        return False
    qt, tt = _TOKEN_RE.findall(q), _TOKEN_RE.findall(t)
    if not qt or len(qt) > len(tt):
        return False
    qs = " ".join(qt)
    if qs in " ".join(tt):
        return True
    n = len(qt)
    best = 0.0
    for i in range(0, len(tt) - n + 1):
        window = " ".join(tt[i : i + n])
        if window[:1] != qs[:1] and best > 0:
            continue
        r = SequenceMatcher(None, qs, window).ratio()
        if r > best:
            if r >= threshold and not numbers_in(quote).issubset(numbers_in(window)):
                continue
            best = r
            if best >= threshold:
                return True
    return best >= threshold


def best_span(fact: str, text: str, min_ratio: float = 0.8) -> str | None:
    """Find the span of `text` that best matches `fact`; returns the ORIGINAL
    span text (so key facts become verbatim), or None if nothing is close."""
    nf = normalize(fact)
    if not nf:
        return None
    words = list(re.finditer(r"\S+", text))
    if not words:
        return None
    flen = len(nf.split())
    best, best_span_txt = 0.0, None
    for size in {max(1, flen - 1), flen, flen + 1, flen + 2}:
        for i in range(0, max(1, len(words) - size + 1)):
            j = min(len(words), i + size)
            span = text[words[i].start() : words[j - 1].end()]
            r = SequenceMatcher(None, nf, normalize(span)).ratio()
            if r > best:
                best, best_span_txt = r, span
    if best >= min_ratio and best_span_txt:
        if numbers_in(fact) and not numbers_in(fact).issubset(numbers_in(best_span_txt)):
            return None
        return best_span_txt.strip(" ,;:.()[]\"'")
    # fallback: shortest window holding >=80% of the fact's content words and all its numbers
    ftoks = set(content_tokens(fact))
    fnums = numbers_in(fact)
    if len(ftoks) < 2:
        return None
    wtoks = [set(content_tokens(w.group(0))) for w in words]
    max_len = max(4, 2 * flen)
    best_win = None
    for i in range(len(words)):
        acc: set = set()
        for j in range(i, min(len(words), i + max_len)):
            acc |= wtoks[j]
            if len(acc & ftoks) / len(ftoks) >= 0.8:
                span = text[words[i].start() : words[j].end()]
                if fnums.issubset(numbers_in(span)) and (best_win is None or len(span) < len(best_win)):
                    best_win = span
                break
    return best_win.strip(" ,;:.()[]\"'") if best_win else None


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+\s*(?:[-*•]|\d+[.)])\s+|\n{2,}")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip(" -*•\t") for p in _SENT_RE.split(text or "")]
    return [p for p in parts if len(p) > 2]


_REFUSAL_RE = re.compile(
    r"\b(i\s*(?:can(?:'|no)?t|cannot|am unable to|am not able to|do not have|don't have|"
    r"couldn't find|could not find|won't be able)|not (?:covered|included|available|mentioned|"
    r"addressed|specified|found) in|outside (?:of )?(?:my|the|this) (?:scope|remit|documents?)|"
    r"(?:no|not enough) (?:relevant )?information|unable to (?:answer|help|provide)|"
    r"beyond (?:my|the) scope|i'?m (?:sorry|afraid)|please (?:contact|consult|reach out))",
    re.I,
)


def looks_like_refusal(text: str) -> bool:
    return bool(_REFUSAL_RE.search(text or ""))


def jaccard(a: str, b: str) -> float:
    sa, sb = set(content_tokens(a)), set(content_tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def truncate(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"
