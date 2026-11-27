"""Structure-aware chunking with contextual headers.

* Chunks never cross a section boundary (a policy clause stays whole).
* Each chunk carries a header "[Document title > Section]" that is embedded and
  indexed with it - small models retrieve far better when a chunk says what
  it is part of.
* Table rows become one chunk per row ("col: value; ..."), so a catalogue row
  can be cited exactly; long tables are also queryable by the csv_lookup tool.
* Chunk ids are stable: "<doc_id>#<n>" with n assigned in reading order.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from forgeai.ingest.loaders import Document


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_path: str
    heading: str
    text: str           # body only
    page: int | None = None
    kind: str = "text"  # text | row

    @property
    def header(self) -> str:
        return f"[{self.doc_path}{' > ' + self.heading if self.heading else ''}]"

    @property
    def indexed_text(self) -> str:
        return f"{self.header}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Chunk":
        return Chunk(**d)


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[-*•]|\d+[.)]\s)", text) if p.strip()]
    units: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            units.append(p)
            continue
        sents = re.split(r"(?<=[.!?;])\s+", p)
        buf = ""
        for s in sents:
            while len(s) > max_chars:              # pathological: no punctuation
                units.append(s[:max_chars])
                s = s[max_chars - overlap :]
            if len(buf) + len(s) + 1 > max_chars and buf:
                units.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            units.append(buf)
    chunks: list[str] = []
    buf = ""
    for u in units:
        if buf and len(buf) + len(u) + 2 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            cut = tail.find(" ")
            tail = tail[cut + 1 :] if cut >= 0 else tail
            buf = f"{tail}\n{u}".strip() if tail and len(tail) + len(u) + 2 <= max_chars else u
        else:
            buf = f"{buf}\n\n{u}".strip() if buf else u
    if buf:
        chunks.append(buf)
    return chunks


def _row_text(row: dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in row.items() if str(v).strip())


def chunk_documents(docs: list[Document], max_chars: int = 900, overlap: int = 120,
                    min_chars: int = 40) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        n = 0
        if doc.table is not None:
            for i, row in enumerate(doc.table.rows):
                out.append(Chunk(f"{doc.doc_id}#r{i + 1}", doc.doc_id, doc.path, f"row {i + 1}",
                                 _row_text(row), None, "row"))
            continue
        pending: Chunk | None = None
        for sec in doc.sections:
            body = sec.text.strip()
            if not body:
                continue
            for piece in _split_long(body, max_chars, overlap):
                if len(piece) < min_chars and pending is not None and pending.heading == sec.heading \
                        and len(pending.text) + len(piece) < max_chars * 1.2:
                    pending.text += "\n" + piece
                    continue
                n += 1
                pending = Chunk(f"{doc.doc_id}#{n}", doc.doc_id, doc.path, sec.heading, piece, sec.page)
                out.append(pending)
    return out
