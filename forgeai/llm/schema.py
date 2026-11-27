"""A small JSON-Schema validator (the subset ForgeAI's schemas use).

Structured decoding in Ollama / llama.cpp constrains *syntax*, but small models
still produce empty strings, wrong enums or missing keys when the grammar is
loose, and OpenAI-compatible servers vary in how strictly they enforce schemas.
So every model output is validated here, and failures are fed back to the
model for a bounded number of repair attempts.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = False
        for ty in types:
            py = _TYPES.get(ty)
            if py is None:
                continue
            if ty in ("integer", "number") and isinstance(value, bool):
                continue
            if ty == "integer" and isinstance(value, float) and value.is_integer():
                ok = True
                break
            if isinstance(value, py):
                ok = True
                break
        if not ok:
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: string shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: string longer than {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: at most {schema['maxItems']} items allowed")
        if "items" in schema:
            for i, item in enumerate(value):
                errs.extend(validate(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required key '{key}'")
        for key, sub in props.items():
            if key in value:
                errs.extend(validate(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                errs.append(f"{path}: unexpected keys {sorted(extra)}")
    return errs


def coerce(value: Any, schema: dict) -> Any:
    """Cheap, safe repairs before validation: drop unknown keys when
    additionalProperties is false, clip over-long arrays, cast numeric strings."""
    t = schema.get("type")
    if isinstance(value, dict) and (t == "object" or "properties" in schema):
        props = schema.get("properties", {})
        out = {}
        for k, v in value.items():
            if k in props:
                out[k] = coerce(v, props[k])
            elif schema.get("additionalProperties") is not False:
                out[k] = v
        return out
    if isinstance(value, list) and t == "array":
        items = schema.get("items")
        vals = [coerce(v, items) if items else v for v in value]
        if "maxItems" in schema:
            vals = vals[: schema["maxItems"]]
        return vals
    if isinstance(value, str) and t in ("number", "integer"):
        try:
            f = float(value.strip())
            return int(f) if t == "integer" else f
        except ValueError:
            return value
    if isinstance(value, str) and t == "boolean" and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    if isinstance(value, str) and t == "array":
        return [value] if value.strip() else []
    if isinstance(value, str) and "enum" in schema:
        for e in schema["enum"]:
            if isinstance(e, str) and e.lower() == value.strip().lower():
                return e
    return value


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply that may contain fences or chatter."""
    text = (text or "").strip()
    text = re.sub(r"^<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no JSON object found in model output")


def obj(properties: dict, required: list[str] | None = None) -> dict:
    """Helper to declare a closed object schema."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def arr(items: dict, min_items: int = 0, max_items: int | None = None) -> dict:
    s: dict = {"type": "array", "items": items, "minItems": min_items}
    if max_items is not None:
        s["maxItems"] = max_items
    return s


STR = {"type": "string"}
NESTR = {"type": "string", "minLength": 1}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}
NUM = {"type": "number"}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}
