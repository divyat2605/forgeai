"""The tool registry the factory chooses from.

Each tool declares what it is FOR (capabilities), what it NEEDS (preconditions
the factory checks deterministically, e.g. csv_lookup needs a table in the
corpus) and its argument schema. The factory may only attach a tool when a
requirement names a need the tool serves; the optimizer later prunes tools the
agent never used. An HR agent with a weather tool is a factory defect, and
both checks exist to make that impossible rather than unlikely.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import math
import operator
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from forgeai.util.text import normalize


@dataclass
class ToolSpec:
    name: str
    description: str
    capabilities: list[str]        # needs this tool serves (used for matching + reporting)
    not_for: list[str]             # explicit anti-uses
    arguments: dict                # JSON schema of arguments
    arg_help: str                  # one-line usage for the agent prompt
    requires: str = ""             # precondition id checked by the factory
    network: bool = False
    need: str = ""                 # regex: wording in a requirement that evidences a need for this tool
    external_data: bool = False    # brings information the documents cannot contain (live / today)
    live_need: str = ""            # stricter regex: the topic is ABOUT that live information


REGISTRY: dict[str, ToolSpec] = {
    "csv_lookup": ToolSpec(
        name="csv_lookup",
        description="Exact lookup / filtering over tabular files (CSV, TSV, XLSX) in the knowledge folder.",
        capabilities=["look up rows, prices, stock, part numbers, SKUs, codes, quantities or attributes in a table",
                      "filter or compare records in a catalogue, list, register or schedule"],
        not_for=["questions answered by prose policy text"],
        arguments={"type": "object", "properties": {
            "table": {"type": "string"}, "column": {"type": "string"},
            "op": {"type": "string", "enum": ["equals", "contains", "less_than", "greater_than", "search"]},
            "value": {"type": "string"}}, "required": ["op", "value"]},
        arg_help='{"table": "<table name>", "column": "<column>", "op": "equals|contains|less_than|greater_than|search", "value": "<value>"}  (op "search" matches any column)',
        requires="table_in_corpus",
        need=r"\b(?:catalog(?:ue)?s?|parts?|sku|items?|stock|inventory|price lists?|part numbers?|records?|"
             r"register|lead times?|availability|table)\b",
    ),
    "calculator": ToolSpec(
        name="calculator",
        description="Exact arithmetic on numbers taken from the documents (totals, pro-rata, percentages, unit conversions).",
        capabilities=["compute totals, costs, quantities, differences, percentages, pro-rata entitlements or conversions"],
        not_for=["looking things up", "dates"],
        arguments={"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
        arg_help='{"expression": "e.g. 12 * 450 * 1.18"}',
        need=r"\b(?:calculat\w*|comput\w*|totals?|sum|order value|quantit(?:y|ies)|percent\w*|pro-?rat\w*|"
             r"convert\w*|multipl\w*|work out)\b",
    ),
    "weather": ToolSpec(
        name="weather",
        description="Current conditions and a short daily forecast for a named place (open-meteo, keyless public API).",
        capabilities=["current or forecast weather, wind, rain or temperature at a port, city or location"],
        not_for=["anything not about weather"],
        arguments={"type": "object", "properties": {"location": {"type": "string"},
                                                    "days": {"type": "integer"}}, "required": ["location"]},
        arg_help='{"location": "Rotterdam", "days": 3}',
        network=True,
        need=r"\b(?:weather|wind|rain|storms?|forecasts?|temperature|sea state|swell|waves?|visibility|meteo\w*)\b",
        external_data=True,
        live_need=r"\b(?:weather|forecasts?|wind speed|sea state|meteo\w*)\b",
    ),
    "current_date": ToolSpec(
        name="current_date",
        description="Today's date, weekday and time (needed for deadlines, 'how many days until', 'is it still valid').",
        capabilities=["know today's date to compute deadlines, ages of requests, validity windows, days remaining or elapsed"],
        not_for=["static facts that do not depend on today's date"],
        arguments={"type": "object", "properties": {}, "required": []},
        arg_help="{}",
        need=r"\b(?:today|deadlines?|days? (?:left|remaining|until|since|ago)|expir\w*|overdue|elapsed|"
             r"how long ago|how many days (?:until|since|left)|countdown|current date)\b",
        external_data=True,
        live_need=r"\b(?:today'?s? date|current date|what day is it|days? (?:left|remaining|until|since)|how many days (?:until|since|left)|overdue|countdown)\b",
    ),
}


# ------------------------------------------------------------------ calculator
_OPS: dict[type, Callable] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS: dict[str, Callable] = {"round": round, "min": min, "max": max, "abs": abs, "sqrt": math.sqrt,
                               "ceil": math.ceil, "floor": math.floor, "sum": lambda *a: sum(a)}


def safe_eval(expr: str) -> float:
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/")
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)          # 1,200 -> 1200
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)   # 18% -> (18/100)
    expr = re.sub(r"[₹$€£]|\b(?:rs|inr|usd|eur)\b\.?", "", expr, flags=re.I)
    tree = ast.parse(expr.strip(), mode="eval")

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    val = ev(tree)
    if isinstance(val, float) and (math.isinf(val) or math.isnan(val)):
        raise ValueError("result is not finite")
    return val


def _fmt_num(v: float) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return str(v)
    return f"{v:.6f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------ csv lookup
def _num(s: Any) -> float | None:
    try:
        return float(re.sub(r"[^\d.\-]", "", str(s)) or "x")
    except ValueError:
        return None


class ToolBox:
    """Executes tool calls for one agent. Tables are given by the definition."""

    def __init__(self, enabled: list[str], tables: dict[str, dict] | None = None,
                 timezone_offset_hours: float = 5.5, now: Callable[[], _dt.datetime] | None = None,
                 offline: bool = False, record: dict | None = None):
        self.enabled = [t for t in enabled if t in REGISTRY]
        self.record = record          # network results, recorded so replays get the same tool results
        self.tables = tables or {}       # name -> {"columns": [...], "rows": [...], "doc_id": ...}
        self.tz = _dt.timezone(_dt.timedelta(hours=timezone_offset_hours))
        self._now = now
        self.offline = offline

    def describe(self) -> str:
        lines = []
        for name in self.enabled:
            spec = REGISTRY[name]
            extra = ""
            if name == "csv_lookup" and self.tables:
                extra = " Tables: " + "; ".join(f"{t} (columns: {', '.join(v['columns'])})" for t, v in self.tables.items())
            lines.append(f"- {name}: {spec.description}{extra}\n  arguments: {spec.arg_help}")
        return "\n".join(lines)

    def run(self, name: str, args: dict) -> dict:
        if name not in self.enabled:
            return {"ok": False, "error": f"tool '{name}' is not attached to this agent"}
        try:
            if name == "calculator":
                expr = str(args.get("expression", ""))
                return {"ok": True, "result": f"{expr} = {_fmt_num(safe_eval(expr))}"}
            if name == "current_date":
                now = self._now() if self._now else _dt.datetime.now(self.tz)
                return {"ok": True, "result": now.strftime("Today is %A, %d %B %Y (%Y-%m-%d), time %H:%M, ISO week %V.")}
            if name == "csv_lookup":
                return self._csv(args)
            if name == "weather":
                key = json.dumps(args, sort_keys=True)
                if self.record is not None and key in self.record:
                    return self.record[key]
                r = self._weather(args)
                if self.record is not None and r.get("ok"):
                    self.record[key] = r
                return r
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        return {"ok": False, "error": "unknown tool"}

    def _csv(self, args: dict) -> dict:
        if not self.tables:
            return {"ok": False, "error": "no tables available"}
        tname = str(args.get("table") or "")
        table = self.tables.get(tname)
        if table is None:
            cands = [k for k in self.tables if normalize(tname) and normalize(tname) in normalize(k)]
            table = self.tables[cands[0]] if cands else None
        tables = [table] if table else list(self.tables.values())
        op = str(args.get("op") or "search")
        value = str(args.get("value") or "").strip()
        col_q = normalize(str(args.get("column") or ""))
        out_rows = []
        for t in tables:
            cols = t["columns"]
            col = next((c for c in cols if normalize(c) == col_q), None) or \
                next((c for c in cols if col_q and col_q in normalize(c)), None)
            for i, row in enumerate(t["rows"]):
                cells = [row.get(col, "")] if (col and op != "search") else list(row.values())
                hit = False
                for cell in cells:
                    cn, vn = normalize(str(cell)), normalize(value)
                    if op in ("equals",) and cn == vn:
                        hit = True
                    elif op in ("contains", "search") and vn and (vn in cn or all(w in cn for w in vn.split())):
                        hit = True
                    elif op in ("less_than", "greater_than"):
                        a, b = _num(cell), _num(value)
                        if a is not None and b is not None and ((a < b) if op == "less_than" else (a > b)):
                            hit = True
                if hit:
                    out_rows.append((t, i, row))
        if not out_rows and op == "equals":
            return self._csv({**args, "op": "contains"})
        shown = out_rows[:12]
        lines = [f"{t['doc_id']}#r{i + 1}: " + "; ".join(f"{k}: {v}" for k, v in r.items() if str(v).strip())
                 for t, i, r in shown]
        res = f"{len(out_rows)} matching row(s)" + (" (first 12 shown)" if len(out_rows) > 12 else "")
        return {"ok": True, "result": res + ("\n" + "\n".join(lines) if lines else ""),
                "rows": [f"{t['doc_id']}#r{i + 1}" for t, i, _ in shown]}

    def _weather(self, args: dict) -> dict:
        if self.offline:
            return {"ok": False, "error": "network disabled (offline mode)"}
        loc = str(args.get("location", "")).strip()
        days = max(1, min(7, int(args.get("days") or 3)))
        if not loc:
            return {"ok": False, "error": "location required"}
        q = urllib.parse.urlencode({"name": loc, "count": 1, "language": "en", "format": "json"})
        with urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{q}", timeout=10) as r:
            g = json.loads(r.read().decode("utf-8"))
        if not g.get("results"):
            return {"ok": False, "error": f"place '{loc}' not found"}
        p = g["results"][0]
        q2 = urllib.parse.urlencode({
            "latitude": p["latitude"], "longitude": p["longitude"], "forecast_days": days, "timezone": "auto",
            "current": "temperature_2m,wind_speed_10m,precipitation,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"})
        with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q2}", timeout=10) as r:
            w = json.loads(r.read().decode("utf-8"))
        cur, d = w.get("current", {}), w.get("daily", {})
        lines = [f"{p['name']}, {p.get('country', '')}: now {cur.get('temperature_2m')}°C, wind "
                 f"{cur.get('wind_speed_10m')} km/h, precipitation {cur.get('precipitation')} mm."]
        for i, day in enumerate(d.get("time", [])):
            lines.append(f"{day}: {d['temperature_2m_min'][i]}-{d['temperature_2m_max'][i]}°C, rain "
                         f"{d['precipitation_sum'][i]} mm, max wind {d['wind_speed_10m_max'][i]} km/h")
        return {"ok": True, "result": "\n".join(lines) + "\n(source: open-meteo.com)"}


def tables_from_docs(docs, base: Path | None = None) -> dict[str, dict]:
    out = {}
    for d in docs:
        if getattr(d, "table", None) is not None:
            out[Path(d.path).stem] = {"columns": d.table.columns, "rows": d.table.rows, "doc_id": d.doc_id,
                                      "path": d.path}
    return out
