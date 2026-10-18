"""Durable write-ahead record for conversions with an unproven result.

No expiry: a client timeout does not bound a backend transaction's lifetime.
The advisor runs as one worker; its per-quotation lock serializes dispatches.
"""
from collections.abc import MutableMapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3


class ConversionJournal(MutableMapping):
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("CONVERSION_JOURNAL", ".state/conversions.sqlite3"))

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS conversions (number TEXT PRIMARY KEY, entry TEXT NOT NULL)")
                yield conn
        finally:
            conn.close()

    def __getitem__(self, key):
        with self._connect() as conn:
            row = conn.execute("SELECT entry FROM conversions WHERE number=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        with self._connect() as conn:
            conn.execute("INSERT INTO conversions VALUES (?, ?) ON CONFLICT(number) DO UPDATE SET entry=excluded.entry",
                         (key, json.dumps(value, ensure_ascii=False)))

    def __delitem__(self, key):
        with self._connect() as conn:
            if not conn.execute("DELETE FROM conversions WHERE number=?", (key,)).rowcount:
                raise KeyError(key)

    def __iter__(self):
        with self._connect() as conn:
            return iter([row[0] for row in conn.execute("SELECT number FROM conversions")])

    def __len__(self):
        with self._connect() as conn:
            return conn.execute("SELECT count(*) FROM conversions").fetchone()[0]

