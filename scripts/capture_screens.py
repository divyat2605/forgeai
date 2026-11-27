"""Capture ForgeAI Studio screenshots (docs/screens/*.png) with headless Chrome.

Starts a temporary Studio server, renders each page for a given run, and saves
PNGs used by the README and the brief. Requires Google Chrome or Chromium.

usage: python scripts/capture_screens.py [--run demos/hr-shore-staff/run] [--theme dark]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def chrome() -> str:
    for c in CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return c
    raise SystemExit("Chrome/Chromium not found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="demos/hr-shore-staff/run")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--port", type=int, default=7899)
    a = ap.parse_args()
    out = ROOT / "docs" / "screens"
    out.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen([sys.executable, "-m", "forgeai", "ui", "--port", str(a.port), "--root", str(ROOT), "--no-browser"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{a.port}/api/env", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        q = f"run={a.run}&theme={a.theme}&static=1"
        pages = {"01_overview": ("", "overview"), "02_report": ("", "report/summary"), "03_groundability": ("", "report/guard"),
                 "04_optimizer": ("", "report/optimizer"), "05_cases": ("", "cases"), "06_judge": ("", "report/judge"),
                 "07_explain": ("&scene=3&still=1", "explain"), "08_build": ("", "build")}
        for name, (extra, route) in pages.items():
            url = f"http://127.0.0.1:{a.port}/?{q}{extra}#/{route}"
            dst = out / f"{name}.png"
            subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                            "--window-size=1600,1000", "--virtual-time-budget=9000", f"--screenshot={dst}", url],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            print("saved", dst.relative_to(ROOT), dst.stat().st_size if dst.exists() else "MISSING")
    finally:
        srv.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
