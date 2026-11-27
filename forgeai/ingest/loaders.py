"""Document loaders: PDF, DOCX, XLSX, CSV/TSV, Markdown, TXT, HTML, JSON.

Standard library everywhere except PDF (pypdf). Each loader returns a
Document with plain text plus section markers; CSV/XLSX also keep the table so
the csv_lookup tool can query it exactly. Files that cannot be read (scanned
PDFs with no text layer, binaries) are reported, never silently skipped.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from forgeai.util.io import sha256_file, slugify

TEXT_EXT = {".txt", ".md", ".markdown", ".rst"}
SUPPORTED = TEXT_EXT | {".pdf", ".docx", ".csv", ".tsv", ".xlsx", ".html", ".htm", ".json"}


@dataclass
class Section:
    heading: str
    text: str
    page: int | None = None


@dataclass
class Table:
    columns: list[str]
    rows: list[dict]


@dataclass
class Document:
    doc_id: str
    path: str            # relative, forward slashes
    kind: str
    sha256: str
    title: str
    sections: list[Section]
    table: Table | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join((f"{s.heading}\n{s.text}" if s.heading else s.text) for s in self.sections)

    @property
    def n_chars(self) -> int:
        return sum(len(s.text) for s in self.sections)

    def card(self) -> dict:
        return {
            "doc_id": self.doc_id, "path": self.path, "kind": self.kind, "sha256": self.sha256,
            "title": self.title, "chars": self.n_chars,
            "headings": [s.heading for s in self.sections if s.heading][:40],
            "table_columns": self.table.columns if self.table else None,
            "table_rows": len(self.table.rows) if self.table else None,
            "warnings": self.warnings,
        }


_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+.+|(?:section|article|chapter|part|annex|appendix|clause)\s+[\w.]+.*|"
    r"\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z][^.!?]{2,80}|[A-Z][A-Z0-9 &/,()'-]{3,80})$",
    re.I,
)


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";", ":")) and not s.startswith("#"):
        return False
    if s.startswith("#"):
        return True
    if re.search(r"[.;:]\s+\S", s):        # contains a sentence break -> body text
        return False
    if re.match(r"^(?:section|article|chapter|part|annex|appendix|clause)\s+[\w.]+", s, re.I):
        return True
    if re.match(r"^\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+[A-Z]", s) and len(s.split()) <= 12:
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters) and len(s.split()) <= 10


def _title_line(line: str, nxt: str, prev: str = "", prev_heading: bool = False) -> bool:
    """PDF text has no styling: a short Title-Case line without terminal
    punctuation, followed by a longer sentence-like line, is a heading."""
    s = line.strip()
    words = s.split()
    if not (1 <= len(words) <= 8) or not s[:1].isupper() or s.endswith((".", ",", ";", ":", "?", "!")):
        return False
    if s.startswith(("-", "*", "\u2022")) or re.search(r"\d{3,}", s):
        return False
    caps = sum(1 for w in words if w[:1].isupper() or w.lower() in ("and", "of", "the", "for", "to", "in", "on", "a", "or"))
    n, p = nxt.strip(), prev.strip()
    if p and not prev_heading and not p.endswith((".", ":", "!", "?", ")")) and not _looks_like_heading(p):
        return False          # probably the wrapped tail of a paragraph
    shape_ok = caps == len(words) or len(words) <= 5
    if caps == len(words) and n and len(n.split()) <= 8 and not n.endswith((".", ",", ";")):
        return True           # stacked title lines (document title above a section heading)
    return shape_ok and bool(n) and (len(n) > len(s) * 1.4 or n.endswith((".", ":")))


def _sections_from_text(text: str, page: int | None = None) -> list[Section]:
    sections: list[Section] = []
    heading, buf = "", []
    lines = text.splitlines()
    prev_heading = True
    for i, line in enumerate(lines):
        nxt = next((x for x in lines[i + 1 :] if x.strip()), "")
        prev = next((x for x in reversed(lines[:i]) if x.strip()), "")
        is_head = _looks_like_heading(line) or _title_line(line, nxt, prev, prev_heading)
        if line.strip():
            prev_heading = is_head
        if is_head:
            if any(b.strip() for b in buf) or heading:
                sections.append(Section(heading, "\n".join(buf).strip(), page))
            heading, buf = line.strip().lstrip("#").strip(), []
        else:
            buf.append(line)
    if any(b.strip() for b in buf) or heading:
        sections.append(Section(heading, "\n".join(buf).strip(), page))
    return [s for s in sections if s.text or s.heading]


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path) -> tuple[list[Section], list[str]]:
    from pypdf import PdfReader

    warnings: list[str] = []
    reader = PdfReader(str(path))
    sections: list[Section] = []
    empty = 0
    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            pages.append(_clean(page.extract_text() or ""))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"page {i}: text extraction failed ({e.__class__.__name__})")
            pages.append("")
    # running headers/footers: lines that recur on most pages (digits ignored: "page 3 of 9")
    sig = lambda line: re.sub(r"\d+", "#", line.strip().lower())  # noqa: E731
    counts: dict[str, int] = {}
    for t in pages:
        for line in {sig(x) for x in t.splitlines() if x.strip()}:
            counts[line] = counts.get(line, 0) + 1
    boiler = {k for k, n in counts.items() if len(pages) >= 2 and n >= max(2, 0.5 * len(pages)) and len(k) < 160}
    if boiler:
        warnings.append(f"removed {len(boiler)} running header/footer line(s)")
    for i, t in enumerate(pages, start=1):
        t = "\n".join(x for x in t.splitlines() if sig(x) not in boiler)
        if len(t) < 20:
            empty += 1
            continue
        page_secs = _sections_from_text(t, page=i)
        if page_secs and not page_secs[0].heading and sections:
            page_secs[0].heading = sections[-1].heading      # section continues across the page break
        sections.extend(page_secs)
    if empty and empty == len(reader.pages):
        warnings.append("no text layer (scanned PDF?) - nothing ingested; OCR is out of scope")
    elif empty:
        warnings.append(f"{empty} page(s) had no extractable text")
    return sections, warnings


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def load_docx(path: Path) -> list[Section]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    sections: list[Section] = []
    heading, buf = "", []
    for p in root.iter(f"{_W}p"):
        style = p.find(f"{_W}pPr/{_W}pStyle")
        sval = (style.get(f"{_W}val") if style is not None else "") or ""
        text = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
        if not text:
            continue
        if sval.lower().startswith(("heading", "title")):
            if buf or heading:
                sections.append(Section(heading, "\n".join(buf)))
            heading, buf = text, []
        else:
            buf.append(text)
    if buf or heading:
        sections.append(Section(heading, "\n".join(buf)))
    for tbl in root.iter(f"{_W}tbl"):
        rows = []
        for tr in tbl.iter(f"{_W}tr"):
            cells = ["".join(t.text or "" for t in tc.iter(f"{_W}t")).strip() for tc in tr.iter(f"{_W}tc")]
            rows.append(" | ".join(cells))
        if rows:
            sections.append(Section("Table", "\n".join(rows)))
    return sections


def _table_from_rows(rows: list[list[str]]) -> Table | None:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    header = [h.strip() or f"col{i+1}" for i, h in enumerate(rows[0])]
    seen: dict[str, int] = {}
    for i, h in enumerate(header):
        if h in seen:
            seen[h] += 1
            header[i] = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
    out = []
    for r in rows[1:]:
        r = list(r) + [""] * (len(header) - len(r))
        out.append({header[i]: r[i].strip() for i in range(len(header))})
    return Table(header, out)


def load_csv(path: Path) -> Table | None:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    return _table_from_rows(list(csv.reader(io.StringIO(text), dialect)))


_X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def load_xlsx(path: Path) -> Table | None:
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.iter(f"{_X}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_X}t")))
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets:
            return None
        root = ET.fromstring(z.read(sheets[0]))
    rows: list[list[str]] = []
    for row in root.iter(f"{_X}row"):
        cells: dict[int, str] = {}
        for c in row.iter(f"{_X}c"):
            ref = c.get("r", "A1")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
                col = col * 26 + (ord(ch) - 64)
            v = c.find(f"{_X}v")
            val = v.text if v is not None and v.text is not None else ""
            if c.get("t") == "s" and val:
                val = shared[int(val)]
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{_X}t"))
            cells[col - 1] = val
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return _table_from_rows(rows)


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self._skip = 0
        self._cur: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer"):
            self._skip += 1
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"):
            self._flush()
        if tag in ("h1", "h2", "h3", "h4"):
            self._cur.append("# ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer") and self._skip:
            self._skip -= 1
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._cur.append(data)

    def _flush(self):
        s = " ".join("".join(self._cur).split())
        if s and s != "#":
            self.lines.append(s)
        self._cur = []


def _table_sections(table: Table, title: str) -> list[Section]:
    return [Section(f"{title} (table, {len(table.rows)} rows)",
                    "Columns: " + ", ".join(table.columns))]


def load_document(path: Path, root: Path) -> Document | None:
    ext = path.suffix.lower()
    rel = path.relative_to(root).as_posix()
    doc_id = slugify(path.stem, 32)
    title = path.stem.replace("_", " ").replace("-", " ").strip()
    warnings: list[str] = []
    table = None
    if ext == ".pdf":
        sections, warnings = load_pdf(path)
    elif ext == ".docx":
        sections = load_docx(path)
    elif ext in (".csv", ".tsv"):
        table = load_csv(path)
        sections = _table_sections(table, title) if table else []
    elif ext == ".xlsx":
        table = load_xlsx(path)
        sections = _table_sections(table, title) if table else []
    elif ext in (".html", ".htm"):
        p = _HTMLText()
        p.feed(path.read_text(encoding="utf-8", errors="replace"))
        p._flush()
        sections = _sections_from_text(_clean("\n".join(p.lines)))
    elif ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        sections = [Section(title, json.dumps(data, indent=1, ensure_ascii=False))]
    elif ext in TEXT_EXT:
        sections = _sections_from_text(_clean(path.read_text(encoding="utf-8", errors="replace")))
    else:
        return None
    if table is None and ext in (".csv", ".tsv", ".xlsx"):
        warnings.append("table could not be parsed")
    first_heading = next((s.heading for s in sections if s.heading), "")
    if first_heading and len(first_heading) <= 80 and ext not in (".csv", ".tsv", ".xlsx"):
        title = first_heading
    return Document(doc_id=doc_id, path=rel, kind=ext.lstrip("."), sha256=sha256_file(path), title=title,
                    sections=sections, table=table, warnings=warnings)


def load_folder(folder: Path) -> tuple[list[Document], list[dict]]:
    """Load every supported file under `folder`. Returns (documents, skipped)."""
    folder = Path(folder)
    docs: list[Document] = []
    skipped: list[dict] = []
    used_ids: set[str] = set()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        if path.suffix.lower() not in SUPPORTED:
            skipped.append({"path": rel, "reason": f"unsupported file type '{path.suffix or 'none'}'"})
            continue
        try:
            doc = load_document(path, folder)
        except Exception as e:  # noqa: BLE001
            skipped.append({"path": rel, "reason": f"could not parse: {e.__class__.__name__}: {e}"})
            continue
        if doc is None or (not doc.sections and doc.table is None):
            skipped.append({"path": rel, "reason": "no extractable text"
                            + (f" ({'; '.join(doc.warnings)})" if doc and doc.warnings else "")})
            continue
        base, n = doc.doc_id, 2
        while doc.doc_id in used_ids:
            doc.doc_id = f"{base}-{n}"
            n += 1
        used_ids.add(doc.doc_id)
        docs.append(doc)
    return docs, skipped
