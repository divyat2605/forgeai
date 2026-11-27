"""Content-addressed cache for model calls and embeddings (SQLite, stdlib).

Two layers are used during a run: a machine-wide cache (speeds up re-runs) and
a per-run cache stored inside the run folder. Because the per-run cache holds
every response that produced the run, `forge replay` can re-execute a committed
run on a machine with no model installed (identical artifacts apart from timing fields).
"""

from __future__ import annotations

import sqlite3
import threading
from array import array
from pathlib import Path


class SqliteStore:
    def __init__(self, path: Path, readonly: bool = False):
        self.path = Path(path)
        self.readonly = readonly
        self._lock = threading.Lock()
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if readonly and not self.path.exists():
            self._db = None
            return
        uri = f"file:{self.path.as_posix()}?mode=ro" if readonly else self.path.as_posix()
        self._db = sqlite3.connect(uri, uri=readonly, check_same_thread=False, timeout=30)
        if not readonly:
            self._db.execute("PRAGMA journal_mode=DELETE")
            self._db.execute("CREATE TABLE IF NOT EXISTS chat (k TEXT PRIMARY KEY, content TEXT, tin INT, tout INT)")
            self._db.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, vec BLOB)")
            self._db.commit()

    def get_chat(self, key: str):
        if self._db is None:
            return None
        with self._lock:
            row = self._db.execute("SELECT content, tin, tout FROM chat WHERE k=?", (key,)).fetchone()
        return row

    def put_chat(self, key: str, content: str, tin: int, tout: int) -> None:
        if self.readonly or self._db is None:
            return
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO chat VALUES (?,?,?,?)", (key, content, tin, tout))
            self._db.commit()

    def get_emb(self, key: str):
        if self._db is None:
            return None
        with self._lock:
            row = self._db.execute("SELECT vec FROM emb WHERE k=?", (key,)).fetchone()
        if not row:
            return None
        a = array("f")
        a.frombytes(row[0])
        return list(a)

    def put_emb_many(self, items: list[tuple[str, list[float]]]) -> None:
        if self.readonly or self._db is None or not items:
            return
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO emb VALUES (?,?)",
                                 [(k, array("f", v).tobytes()) for k, v in items])
            self._db.commit()

    def close(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.close()
                self._db = None


class LayeredCache:
    def __init__(self, stores: list[SqliteStore]):
        self.stores = stores

    def get_chat(self, key: str):
        for i, s in enumerate(self.stores):
            row = s.get_chat(key)
            if row is not None:
                for other in self.stores[:i] + self.stores[i + 1 :]:
                    if other.get_chat(key) is None:
                        other.put_chat(key, *row)
                return row
        return None

    def put_chat(self, key: str, content: str, tin: int, tout: int) -> None:
        for s in self.stores:
            s.put_chat(key, content, tin, tout)

    def get_emb(self, key: str):
        for i, s in enumerate(self.stores):
            v = s.get_emb(key)
            if v is not None:
                for other in self.stores[:i] + self.stores[i + 1 :]:
                    if other.get_emb(key) is None:
                        other.put_emb_many([(key, v)])
                return v
        return None

    def put_emb_many(self, items) -> None:
        for s in self.stores:
            s.put_emb_many(items)

    def close(self) -> None:
        for s in self.stores:
            s.close()
