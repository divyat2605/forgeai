"""Factory benchmark: run ForgeAI unattended on briefs it was never tuned on.

For each bench/<name>/ (brief.md + docs/), run `forge build --unattended` and
collect the outcome into bench/RESULTS.md. The mismatch case is EXPECTED to
stop at the groundability guard; stopping there counts as a pass.

usage: python scripts/bench.py [--only it-helpdesk,vessel-sms] [--profile standard] [--max-minutes 30]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECT_STOP = {"mismatch-adversarial"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--profile", default="standard")
    ap.add_argument("--max-minutes", type=float, default=0)
    ap.add_argument("--out", default="bench/runs")
    a = ap.parse_args()
    names = [n for n in sorted(p.name for p in (ROOT / "bench").iterdir() if (p / "brief.md").exists())
             if not a.only or n in a.only.split(",")]
    rows = []
    for name in names:
        b = ROOT / "bench" / name
        t = time.time()
        cmd = [sys.executable, "-m", "forgeai", "build", "--brief-file", str(b / "brief.md"), "--docs", str(b / "docs"),
               "--unattended", "--name", name, "--out", a.out, "--profile", a.profile]
        if a.max_minutes:
            cmd += ["--max-minutes", str(a.max_minutes)]
        print(f"\n=== {name} ===", flush=True)
        rc = subprocess.call(cmd, cwd=ROOT)
        runs = sorted((ROOT / a.out).glob(f"{name}-*"))
        run = runs[-1] if runs else None
        row = {"name": name, "rc": rc, "minutes": round((time.time() - t) / 60, 1), "run": run.relative_to(ROOT).as_posix() if run else ""}
        if run and (run / "report.json").exists():
            r = json.loads((run / "report.json").read_text(encoding="utf-8"))
            ev = json.loads((run / "05_evalset.json").read_text(encoding="utf-8"))["stats"]
            row.update(status="built", holdout=r["holdout"], baseline=r["baseline"]["holdout"], dev=r["dev"],
                       tools=r["tools"], gaps=[g["topic"] for g in r["gaps"]], cases=ev["total"],
                       judge=(r.get("canaries") or {}).get("overall"), failures=r["failures_final"])
        elif run and (run / "03_groundability.json").exists():
            g = json.loads((run / "03_groundability.json").read_text(encoding="utf-8"))
            row.update(status="stopped (not groundable)", coverage=g["coverage"], gaps=[x["topic"] for x in g["gaps"]])
        else:
            row.update(status=f"error rc={rc}")
        row["expected"] = "stop" if name in EXPECT_STOP else "build"
        row["ok"] = (row["status"].startswith("stopped")) == (name in EXPECT_STOP)
        rows.append(row)
    (ROOT / "bench" / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    L = ["# Factory benchmark (briefs the factory was never tuned on)", "",
         "| Brief | Expected | Outcome | Cases | Tools attached | Gaps flagged | Holdout baseline -> final | Judge canaries | Minutes |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("status") == "built":
            h, b = r["holdout"], r["baseline"]
            score = f"{b['passed']}/{b['n']} -> **{h['passed']}/{h['n']}**"
            judge = "" if r["judge"] is None else "%.0f%%" % (100 * r["judge"])
            L.append(f"| {r['name']} | build | built {'OK' if r['ok'] else 'WRONG'} | {r['cases']} | {', '.join(r['tools']) or 'none'} | "
                     f"{'; '.join(r['gaps']) or '-'} | {score} | {judge} | {r['minutes']} |")
        else:
            L.append(f"| {r['name']} | {r['expected']} | {r['status']} {'OK' if r['ok'] else 'WRONG'} | - | - | "
                     f"{'; '.join(r.get('gaps', [])) or '-'} | - | - | {r['minutes']} |")
    (ROOT / "bench" / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
