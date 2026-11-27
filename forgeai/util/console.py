"""Console output that behaves on Windows terminals (cmd, PowerShell, Windows
Terminal) as well as macOS/Linux: UTF-8 forced where possible, ANSI colour only
when the terminal supports it, ASCII fallbacks for symbols."""

from __future__ import annotations

import os
import sys
import threading
import time

_lock = threading.Lock()
_quiet = False


def _enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _setup() -> tuple[bool, bool]:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    color = is_tty and not os.environ.get("NO_COLOR") and _enable_windows_ansi()
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    unicode_ok = "utf" in enc
    return color, unicode_ok


COLOR, UNICODE = _setup()

SYM = {
    "ok": "✔" if UNICODE else "+",
    "fail": "✘" if UNICODE else "x",
    "warn": "⚠" if UNICODE else "!",
    "arrow": "→" if UNICODE else "->",
    "dot": "•" if UNICODE else "*",
    "bar": "█" if UNICODE else "#",
    "light": "░" if UNICODE else ".",
}

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
          "magenta": "35", "cyan": "36", "grey": "90"}


def style(text: str, *styles: str) -> str:
    if not COLOR or not styles:
        return text
    codes = ";".join(_CODES[s] for s in styles if s in _CODES)
    return f"\033[{codes}m{text}\033[0m"


def set_quiet(q: bool) -> None:
    global _quiet
    _quiet = q


def out(msg: str = "") -> None:
    if _quiet:
        return
    with _lock:
        print(msg, flush=True)


def stage(n: int | str, title: str) -> None:
    out()
    out(style(f"[{n}] {title}", "bold", "cyan"))


def info(msg: str) -> None:
    out(f"    {msg}")


def ok(msg: str) -> None:
    out(f"    {style(SYM['ok'], 'green')} {msg}")


def warn(msg: str) -> None:
    out(f"    {style(SYM['warn'] + ' ' + msg, 'yellow')}")


def fail(msg: str) -> None:
    out(f"    {style(SYM['fail'] + ' ' + msg, 'red')}")


def bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(round(frac * width))
    return SYM["bar"] * full + SYM["light"] * (width - full)


class Progress:
    """Minimal thread-safe progress line (no external dependency)."""

    def __init__(self, total: int, label: str):
        self.total, self.label, self.done = max(1, total), label, 0
        self.t0 = time.time()
        self._tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def tick(self, n: int = 1) -> None:
        with _lock:
            self.done += n
            if _quiet:
                return
            frac = self.done / self.total
            el = time.time() - self.t0
            if self._tty:
                sys.stdout.write(f"\r    {self.label} {bar(frac, 20)} {self.done}/{self.total}  {el:5.0f}s ")
                sys.stdout.flush()
            else:   # logs / web UI: one line per quarter
                q = int(frac * 4)
                if q > getattr(self, "_q", 0):
                    self._q = q
                    print(f"    {self.label} {self.done}/{self.total} ({el:.0f}s)", flush=True)

    def close(self) -> None:
        with _lock:
            if not _quiet and self._tty:
                sys.stdout.write("\r" + " " * 78 + "\r")
                sys.stdout.flush()
