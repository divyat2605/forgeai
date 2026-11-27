"""Minimal dependency-free PDF writer (text documents with headings, wrapping
and pagination). Used only to render the synthetic demo corpora as real PDFs,
so the factory's PDF ingestion path is exercised end to end."""

from __future__ import annotations

import textwrap
from pathlib import Path

PAGE_W, PAGE_H, MARGIN = 595, 842, 56          # A4 in points
_SUBS = {"₹": "INR ", "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
         "—": "-", "•": "-", "…": "...", " ": " ", "≤": "<=", "≥": ">=", "×": "x"}


def _latin(s: str) -> str:
    for k, v in _SUBS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, title: str, markdown: str, footer: str = "") -> None:
    """Render simple markdown (#/## headings, paragraphs, '- ' bullets) to PDF."""
    lines: list[tuple[str, float, str]] = [("F2", 16, _latin(title)), ("F1", 10, "")]
    for raw in markdown.splitlines():
        s = _latin(raw.rstrip())
        if not s.strip():
            lines.append(("F1", 10, ""))
            continue
        if s.startswith("#"):
            lvl = len(s) - len(s.lstrip("#"))
            txt = s.lstrip("#").strip()
            lines.append(("F1", 6, ""))
            lines.append(("F2", 13 if lvl <= 2 else 11, txt))
            continue
        bullet = s.lstrip().startswith(("- ", "* "))
        body = s.lstrip()[2:] if bullet else s.strip()
        body = body.replace("**", "")
        width = 92 if not bullet else 88
        wrapped = textwrap.wrap(body, width) or [""]
        for i, w in enumerate(wrapped):
            prefix = ("- " if i == 0 else "  ") if bullet else ""
            lines.append(("F1", 10, prefix + w))
    pages: list[list[tuple[str, float, float, str]]] = [[]]
    y = PAGE_H - MARGIN
    for font, size, txt in lines:
        lh = size * 1.45
        if y - lh < MARGIN + 20:
            pages.append([])
            y = PAGE_H - MARGIN
        y -= lh
        if txt:
            pages[-1].append((font, size, y, txt))
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 2 * len(pages) + 1
    page_ids = []
    for n, pg in enumerate(pages, 1):
        ops = []
        for font, size, y, txt in pg:
            ops.append(f"BT /{font} {size} Tf {MARGIN} {y:.1f} Td ({_esc(txt)}) Tj ET")
        if footer:
            ops.append(f"BT /F1 8 Tf {MARGIN} 28 Td ({_esc(_latin(footer))} - page {n} of {len(pages)}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pid = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                  f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {cid} 0 R >>".encode())
        page_ids.append(pid)
    add(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(page_ids)} >>".encode())
    assert len(objs) == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    info = add(f"<< /Title ({_esc(_latin(title))}) /Producer (ForgeAI demo synthesiser) >>".encode())
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(bytes(out))
