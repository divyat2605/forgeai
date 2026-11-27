"""The declarative agent definition (schema forgeai.agent/1).

One JSON file fully determines an agent: model and decoding, a sectioned
system prompt, knowledge/chunking/retrieval parameters, attached tools with
their justification, the output contract, runtime guards and refusal policy.
The prompt is *sectioned* on purpose: the optimizer patches one section at a
time, so every change is small, attributable and revertible.
"""

from __future__ import annotations

import copy
from pathlib import Path

from forgeai import AGENT_SCHEMA_VERSION
from forgeai.llm.schema import validate
from forgeai.util.io import hash_obj, read_json, write_json

SECTION_ORDER = ["role", "audience_tone", "scope", "grounding", "refusal", "tools", "format"]

OUTPUT_CONTRACT = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Answer for the user, or the refusal message."},
        "citations": {"type": "array", "items": {"type": "string"},
                      "description": "Labels of the passages / tool results the answer relies on, e.g. [\"C2\", \"T1\"]."},
        "refused": {"type": "boolean", "description": "true when the question is out of scope or not answerable from the sources."},
    },
    "required": ["answer", "citations", "refused"],
    "additionalProperties": False,
}

DEFINITION_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "name", "model", "system_prompt", "knowledge", "tools",
                 "output_contract", "guards", "refusal_policy"],
    "properties": {
        "schema_version": {"type": "string", "enum": [AGENT_SCHEMA_VERSION]},
        "name": {"type": "string", "minLength": 1},
        "model": {"type": "object", "required": ["name", "temperature"],
                  "properties": {"name": {"type": "string", "minLength": 1},
                                 "temperature": {"type": "number", "minimum": 0, "maximum": 2}}},
        "system_prompt": {"type": "object", "required": ["sections"], "properties": {"sections": {
            "type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "text"],
                                                      "properties": {"id": {"type": "string"},
                                                                     "text": {"type": "string"}}}}}},
        "knowledge": {"type": "object", "required": ["index_dir", "chunking", "retrieval"], "properties": {
            "chunking": {"type": "object", "required": ["max_chars", "overlap"], "properties": {
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 4000},
                "overlap": {"type": "integer", "minimum": 0, "maximum": 1000}}},
            "retrieval": {"type": "object", "required": ["top_k", "bm25_weight"], "properties": {
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "bm25_weight": {"type": "number", "minimum": 0, "maximum": 1},
                "neighbours": {"type": "integer", "minimum": 0, "maximum": 2}}}}},
        "tools": {"type": "array", "items": {"type": "object", "required": ["name", "reason"]}},
        "guards": {"type": "object", "properties": {
            "min_relevance": {"type": "number", "minimum": 0, "maximum": 1},
            "max_tool_rounds": {"type": "integer", "minimum": 0, "maximum": 4}}},
        "refusal_policy": {"type": "object", "required": ["message"]},
    },
}


def check(defn: dict) -> list[str]:
    errs = validate(defn, DEFINITION_SCHEMA)
    ids = [s["id"] for s in defn.get("system_prompt", {}).get("sections", [])]
    if len(ids) != len(set(ids)):
        errs.append("$.system_prompt.sections: duplicate section ids")
    from forgeai.runtime.tools import REGISTRY
    for t in defn.get("tools", []):
        if t.get("name") not in REGISTRY:
            errs.append(f"$.tools: unknown tool {t.get('name')!r}")
    return errs


def section(defn: dict, sid: str) -> dict | None:
    for s in defn["system_prompt"]["sections"]:
        if s["id"] == sid:
            return s
    return None


def set_section(defn: dict, sid: str, text: str) -> None:
    s = section(defn, sid)
    if s is None:
        defn["system_prompt"]["sections"].append({"id": sid, "text": text})
        order = {k: i for i, k in enumerate(SECTION_ORDER)}
        defn["system_prompt"]["sections"].sort(key=lambda x: order.get(x["id"], 99))
    else:
        s["text"] = text


def render_system_prompt(defn: dict) -> str:
    parts = []
    for s in defn["system_prompt"]["sections"]:
        if s.get("text", "").strip():
            title = s.get("title") or s["id"].replace("_", " ").upper()
            parts.append(f"## {title}\n{s['text'].strip()}")
    return "\n\n".join(parts)


def fingerprint(defn: dict) -> str:
    d = copy.deepcopy(defn)
    d.pop("provenance", None)
    return hash_obj(d)[:12]


def save(defn: dict, path: Path) -> None:
    write_json(path, defn)


def load(path: Path) -> dict:
    defn = read_json(path)
    errs = check(defn)
    if errs:
        raise ValueError(f"invalid agent definition {path}: " + "; ".join(errs[:5]))
    return defn
