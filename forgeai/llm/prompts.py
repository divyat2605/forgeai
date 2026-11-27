"""Prompt files. Every prompt the factory sends lives in forgeai/prompts/*.md
(committed, reviewable, hashed into each run manifest). File format:

    ---
    id: evalgen.answerable
    purpose: one line
    ---
    ## system
    ...
    ## user
    ... {{variable}} ...
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from forgeai.util.io import sha256_text

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@lru_cache(maxsize=None)
def load(prompt_id: str) -> dict:
    path = PROMPT_DIR / f"{prompt_id}.md"
    raw = path.read_text(encoding="utf-8")
    body = raw
    meta: dict = {}
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        for line in front.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    parts = re.split(r"^## (system|user)\s*$", body, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "user" not in sections:
        raise ValueError(f"prompt {prompt_id} has no '## user' section")
    return {"id": prompt_id, "meta": meta, "system": sections.get("system", ""),
            "user": sections["user"], "sha256": sha256_text(raw)}


def render(prompt_id: str, **variables) -> tuple[str, str, str]:
    p = load(prompt_id)

    def sub(text: str) -> str:
        def rep(m: re.Match) -> str:
            key = m.group(1)
            if key not in variables:
                raise KeyError(f"prompt {prompt_id} needs variable '{key}'")
            return str(variables[key])
        return _VAR.sub(rep, text)

    return sub(p["system"]), sub(p["user"]), p["sha256"]


def all_prompt_hashes() -> dict[str, str]:
    return {p.stem: load(p.stem)["sha256"] for p in sorted(PROMPT_DIR.glob("*.md"))}
