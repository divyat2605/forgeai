"""Synthesise a demo / benchmark corpus with a local model.

Each corpus folder holds `synthesis/spec.json`:
  {"documents": [{"file": "leave_policy.pdf", "title": "...", "prompt": "synthesis/leave.md"}, ...],
   "tables": [{"file": "catalogue.csv", "generator": "spares_catalogue"}]}
Prompt files contain a FACT SHEET the document must state, so the corpus has
known, checkable facts. Prompts are committed with the corpus.

usage: python scripts/synthesize.py demos/hr-shore-staff [--model qwen3.6] [--force]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdfwriter import write_pdf  # noqa: E402

SYSTEM = ("You write realistic internal company documents. Output GitHub markdown only: '#'/'##' headings, short "
          "paragraphs and '-' bullets. No tables. State every fact from the FACT SHEET exactly as given (same numbers, "
          "names and units), in natural prose, spread across sensible sections. You may add plausible procedural detail, "
          "but never add numbers, amounts or durations that are not in the fact sheet.")


def ollama(model: str, prompt: str, host: str = "http://localhost:11434") -> str:
    body = {"model": model, "stream": False, "think": False, "keep_alive": "30m",
            "options": {"temperature": 0.4, "seed": 11, "num_ctx": 8192, "num_predict": 3500},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        txt = json.loads(r.read().decode())["message"]["content"]
    txt = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", txt.strip())
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()


# ---------------------------------------------------------------- tables
def spares_catalogue(path: Path, rng: random.Random) -> None:
    systems = {
        "Main Engine": ["Fuel injection valve", "Exhaust valve spindle", "Piston ring set", "Cylinder liner O-ring kit",
                        "Turbocharger bearing", "Starting air valve"],
        "Auxiliary Engine": ["Fuel pump plunger", "Cooling water pump seal", "Thermostat element", "Lube oil filter cartridge"],
        "Purifier": ["Bowl gasket set", "Vertical shaft bearing", "Friction pad set"],
        "Pumps": ["Mechanical seal 45mm", "Impeller bronze 180mm", "Wear ring set"],
        "Deck Machinery": ["Windlass brake lining", "Mooring winch clutch pin", "Hydraulic hose 1/2in 2m"],
        "Electrical": ["Circuit breaker 63A", "Insulation monitor relay", "LED floodlight 150W"],
        "Safety": ["Lifejacket light", "SCBA cylinder 6.8L", "Fire hose coupling 2.5in"],
    }
    makers = {"Main Engine": ["MAN B&W", "WinGD"], "Auxiliary Engine": ["Yanmar", "Daihatsu"], "Purifier": ["Alfa Laval"],
              "Pumps": ["Shinko", "Azcue"], "Deck Machinery": ["Kawasaki", "MacGregor"], "Electrical": ["Terasaki", "ABB"],
              "Safety": ["Viking", "Drager"]}
    suppliers = ["SUP-01", "SUP-02", "SUP-03"]
    rows = []
    n = 1
    for sysname, items in systems.items():
        for item in items:
            maker = rng.choice(makers[sysname])
            price = round(rng.uniform(18, 4200) / 5) * 5
            rows.append({
                "part_no": f"{sysname[:2].upper()}-{1000 + n * 7}",
                "description": item, "system": sysname, "maker": maker,
                "unit_price_usd": f"{price:.2f}", "stock_qty": rng.choice([0, 0, 2, 4, 6, 10, 12, 25, 40]),
                "lead_time_days": rng.choice([3, 5, 7, 10, 14, 21, 30, 45]),
                "supplier_id": rng.choice(suppliers), "min_order_qty": rng.choice([1, 1, 1, 2, 5, 10]),
                "critical_spare": rng.choice(["yes", "no", "no"]),
            })
            n += 1
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_docx(path: Path, title: str, md: str) -> None:
    import zipfile
    from xml.sax.saxutils import escape
    paras = [("Title", title)]
    for line in md.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("#"):
            paras.append(("Heading1" if t.startswith("# ") or t.startswith("## ") else "Heading2", t.lstrip("#").strip()))
        else:
            paras.append(("", t.lstrip("-* ").replace("**", "")))
    body = "".join(("<w:p>" + (f'<w:pPr><w:pStyle w:val="{st}"/></w:pPr>' if st else "") +
                    f"<w:r><w:t xml:space=\"preserve\">{escape(tx)}</w:t></w:r></w:p>") for st, tx in paras)
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
          'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


def write_html(path: Path, title: str, md: str) -> None:
    from html import escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title></head><body>",
           "<nav>Home | Courses | Contact</nav>", f"<h1>{escape(title)}</h1>"]
    for line in md.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("#"):
            out.append(f"<h2>{escape(t.lstrip('#').strip())}</h2>")
        elif t.startswith(("- ", "* ")):
            out.append(f"<li>{escape(t[2:].replace('**', ''))}</li>")
        else:
            out.append(f"<p>{escape(t.replace('**', ''))}</p>")
    out.append("<footer>(c) fictional organisation</footer></body></html>")
    path.write_text("\n".join(out), encoding="utf-8")


def product_prices_xlsx(path: Path, rng: random.Random) -> None:
    import zipfile
    from xml.sax.saxutils import escape
    rows = [["sku", "product", "plan", "monthly_price_usd", "max_users", "support_level"]]
    for i, (prod, plans) in enumerate({"FlowDesk": ["Starter", "Team", "Business"],
                                        "FlowDesk Analytics": ["Basic", "Pro"],
                                        "FlowDesk Mobile": ["Standard"]}.items()):
        for j, plan in enumerate(plans):
            rows.append([f"FD-{i + 1}{j + 1:02d}", prod, plan, f"{rng.choice([9, 19, 29, 49, 79, 99, 149])}",
                         str(rng.choice([3, 10, 25, 100, 500])), rng.choice(["email", "email + chat", "24/7 phone"])])
    shared: list[str] = []
    def sidx(v):
        if v not in shared:
            shared.append(v)
        return shared.index(v)
    sheet = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if r > 1 and v.replace(".", "").isdigit():
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="s"><v>{sidx(v)}</v></c>')
        sheet.append(f'<row r="{r}">{"".join(cells)}</row>')
    S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{S}"><sheetData>{"".join(sheet)}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{S}">' + "".join(f"<si><t>{escape(x)}</t></si>" for x in shared) + "</sst>")


GENERATORS = {"spares_catalogue": spares_catalogue, "product_prices_xlsx": product_prices_xlsx}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--model", default="qwen3.6")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    root = Path(a.corpus)
    spec = json.loads((root / "synthesis" / "spec.json").read_text(encoding="utf-8"))
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for t in spec.get("tables", []):
        out = docs / t["file"]
        if out.exists() and not a.force:
            continue
        GENERATORS[t["generator"]](out, random.Random(t.get("seed", 3)))
        print("table", out)
    for d in spec["documents"]:
        out = docs / d["file"]
        md_out = root / "synthesis" / "rendered" / (Path(d["file"]).stem + ".md")
        if out.exists() and not a.force:
            continue
        prompt = (root / d["prompt"]).read_text(encoding="utf-8")
        md = md_out.read_text(encoding="utf-8") if md_out.exists() and not a.force else ollama(a.model, prompt)
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(md + "\n", encoding="utf-8")
        if out.suffix == ".pdf":
            write_pdf(out, d["title"], md, footer=d.get("footer", d["title"]))
        elif out.suffix == ".docx":
            write_docx(out, d["title"], md)
        elif out.suffix in (".html", ".htm"):
            write_html(out, d["title"], md)
        else:
            out.write_text(f"# {d['title']}\n\n{md}\n", encoding="utf-8")
        print("doc", out, len(md), "chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
