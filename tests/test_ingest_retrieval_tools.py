import datetime as dt
import sys
import zipfile
from pathlib import Path

import pytest

from forgeai.ingest import chunk_documents, load_folder
from forgeai.retrieval.index import KnowledgeIndex
from forgeai.runtime.tools import ToolBox, safe_eval, tables_from_docs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pdfwriter import write_pdf  # noqa: E402


def _docx(path: Path, paras: list[tuple[str, str]]) -> None:
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    def para(style: str, text: str) -> str:
        ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
        return "<w:p>" + ppr + "<w:r><w:t>" + text + "</w:t></w:r></w:p>"

    body = "".join(para(style, text) for style, text in paras)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def _xlsx(path: Path) -> None:
    S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    shared = f'<sst xmlns="{S}"><si><t>part_no</t></si><si><t>price</t></si><si><t>ME-1007</t></si></sst>'
    sheet = (f'<worksheet xmlns="{S}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             f'<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>415.5</v></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    write_pdf(d / "leave.pdf", "Leave Policy", "# Annual leave\nStaff get 24 days of annual leave per year.\n\n"
              "# Sick leave\nSick leave is 12 days per year. A medical certificate is needed after 2 days.")
    (d / "notes.md").write_text("# Remote work\nUp to 2 remote days per week.\n", encoding="utf-8")
    (d / "parts.csv").write_text("part_no,description,unit_price_usd,stock_qty\nME-1007,Fuel valve,415.50,4\n"
                                 "AU-1050,Pump seal,88.00,0\n", encoding="utf-8")
    _docx(d / "conduct.docx", [("Heading1", "Gifts"), ("", "Gifts above INR 2,000 must be declined.")])
    _xlsx(d / "prices.xlsx")
    (d / "image.png").write_bytes(b"\x89PNG....")
    return d


def test_load_every_format_and_report_skips(corpus):
    docs, skipped = load_folder(corpus)
    kinds = sorted(d.kind for d in docs)
    assert kinds == ["csv", "docx", "md", "pdf", "xlsx"]
    assert skipped and skipped[0]["path"] == "image.png"
    pdf = next(d for d in docs if d.kind == "pdf")
    assert "24 days" in pdf.text and any(s.heading == "Annual leave" for s in pdf.sections)
    xl = next(d for d in docs if d.kind == "xlsx")
    assert xl.table.rows[0]["part_no"] == "ME-1007"
    assert all("\\" not in d.path for d in docs)


def test_chunks_are_stable_and_rows_are_citable(corpus):
    docs, _ = load_folder(corpus)
    a = [c.chunk_id for c in chunk_documents(docs)]
    b = [c.chunk_id for c in chunk_documents(docs)]
    assert a == b and len(set(a)) == len(a)
    assert any(cid.startswith("parts#r") for cid in a)


def test_bm25_only_retrieval_finds_exact_codes(corpus, tmp_path):
    docs, _ = load_folder(corpus)
    idx = KnowledgeIndex.build(chunk_documents(docs), None)
    hits = idx.search("price of ME-1007", top_k=3)
    assert hits and hits[0].chunk.kind == "row" and "ME-1007" in hits[0].chunk.text
    idx.save(tmp_path / "k")
    again = KnowledgeIndex.load(tmp_path / "k")
    assert [h.chunk.chunk_id for h in again.search("medical certificate", top_k=2)][0].startswith("leave")


def test_calculator_is_safe_and_exact():
    assert safe_eval("12 * 415.50") == 4986.0
    assert safe_eval("1,200 + 18%") == 1200.18
    assert safe_eval("round(100/3, 2)") == 33.33
    for bad in ("__import__('os').system('x')", "().__class__", "open('f')", "9**999999"):
        with pytest.raises(Exception):
            safe_eval(bad)


def test_csv_lookup_and_date(corpus):
    docs, _ = load_folder(corpus)
    tb = ToolBox(["csv_lookup", "current_date"], tables_from_docs(docs),
                 now=lambda: dt.datetime(2026, 11, 27, 10, 0))
    r = tb.run("csv_lookup", {"table": "parts", "column": "part_no", "op": "equals", "value": "me-1007"})
    assert r["ok"] and "415.50" in r["result"] and r["rows"] == ["parts#r1"]
    r = tb.run("csv_lookup", {"column": "stock_qty", "op": "less_than", "value": "1"})
    assert "AU-1050" in r["result"]
    assert "27 November 2026" in tb.run("current_date", {})["result"]
    assert not tb.run("weather", {"location": "x"})["ok"]          # not attached -> refused
