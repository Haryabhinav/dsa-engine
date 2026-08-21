"""Dialect-aware persistence — SQLite for development, Postgres for deployment.

Why both, rather than picking one:

  * **SQLite is correct below one app host.** It is transactional, auditable and
    has zero operational surface. Nothing about this workload needs a server
    while everything runs in one process.
  * **Postgres is required at more than one app host.** SQLite is a *file*: one
    writer at a time, and two application servers cannot safely share it. That
    is the threshold — not throughput, which SQLite handles comfortably here.

So the dialect is a deployment decision, and this module is where it lives.

The four incompatibilities that make this a real migration rather than a
find-and-replace (see BUILD_LOG S7):

    SQLite                              Postgres
    INTEGER PRIMARY KEY AUTOINCREMENT   GENERATED ALWAYS AS IDENTITY
    INSERT OR REPLACE INTO t VALUES     INSERT ... ON CONFLICT (pk) DO UPDATE
    connection.executescript(...)       no equivalent; split the statements
    ? placeholders                      %s placeholders

An earlier comment in knowledge.py claimed migration was "a connection-string
change plus a closure-table refresh". That was wrong, and this module is the
correction.
"""
from __future__ import annotations

import os
import pathlib
import re
import sqlite3
from typing import Any, Iterable, Optional, Sequence

SQLITE, POSTGRES = "sqlite", "postgres"


# --------------------------------------------------------------------------
# Schema, expressed once per dialect
# --------------------------------------------------------------------------
def schema(dialect: str) -> list[str]:
    serial = ("INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == SQLITE
              else "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
    return [
        """CREATE TABLE IF NOT EXISTS concept (
             id TEXT PRIMARY KEY, name TEXT NOT NULL,
             description TEXT, scc_id TEXT)""",
        """CREATE TABLE IF NOT EXISTS concept_edge (
             parent TEXT NOT NULL, child TEXT NOT NULL,
             kind TEXT NOT NULL DEFAULT 'PREREQUISITE_OF',
             weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
             approved INTEGER NOT NULL DEFAULT 0,
             redundant INTEGER NOT NULL DEFAULT 0,
             PRIMARY KEY (parent, child, kind))""",
        """CREATE TABLE IF NOT EXISTS concept_closure (
             ancestor TEXT NOT NULL, descendant TEXT NOT NULL,
             depth INTEGER NOT NULL,
             PRIMARY KEY (ancestor, descendant))""",
        """CREATE TABLE IF NOT EXISTS mastery (
             student TEXT NOT NULL, concept TEXT NOT NULL,
             stability DOUBLE PRECISION NOT NULL DEFAULT 3.0,
             last_review DOUBLE PRECISION NOT NULL,
             seen INTEGER NOT NULL DEFAULT 0,
             PRIMARY KEY (student, concept))""",
        f"""CREATE TABLE IF NOT EXISTS review_event (
             id {serial},
             student TEXT, concept TEXT, outcome TEXT, source TEXT,
             ts DOUBLE PRECISION)""",
        """CREATE TABLE IF NOT EXISTS fault_signature (
             sig TEXT PRIMARY KEY, concept TEXT NOT NULL)""",
    ]


# `DOUBLE PRECISION` is spelled REAL in SQLite but SQLite accepts the ANSI name
# via type affinity, so one DDL string serves both. That is the only place the
# two dialects agree by luck rather than by design — everything else is explicit.


class Row(dict):
    """Rows behave like sqlite3.Row (`row["col"]`) on both backends, so callers
    do not branch on dialect."""


class Rows(list):
    """A materialised result set that is BOTH iterable and cursor-shaped.

    Callers already written against sqlite3 use `.fetchall()` / `.fetchone()`;
    newer ones just iterate. Supporting both keeps the migration from rippling
    into every call site, which is where a database swap usually goes wrong.
    """

    def fetchall(self) -> list["Row"]:
        return list(self)

    def fetchone(self) -> Optional["Row"]:
        return self[0] if self else None


class Store:
    """A thin connection shim. Deliberately NOT an ORM: the queries in this
    project are hand-written and readable, and an ORM would hide exactly the
    dialect differences this module exists to make explicit."""

    def __init__(self, dsn: Optional[str] = None, path: Optional[str | pathlib.Path] = None):
        dsn = dsn or os.environ.get("DSA_DATABASE_URL")
        if dsn:
            import psycopg2
            import psycopg2.extras
            self.dialect = POSTGRES
            self.con = psycopg2.connect(dsn)
            self._cursor_kw = {"cursor_factory": psycopg2.extras.RealDictCursor}
        else:
            self.dialect = SQLITE
            self.con = sqlite3.connect(str(path or "knowledge.db"))
            self.con.row_factory = sqlite3.Row
            self._cursor_kw = {}
        self._init_schema()

    # -- dialect plumbing ------------------------------------------------
    def _q(self, sql: str) -> str:
        """`?` is the DB-API placeholder for sqlite3; psycopg2 wants `%s`.
        Naive replacement would corrupt `?` inside string literals, so only
        placeholders outside quotes are translated."""
        if self.dialect == SQLITE:
            return sql
        out, in_str = [], False
        for ch in sql:
            if ch == "'":
                in_str = not in_str
            out.append("%s" if (ch == "?" and not in_str) else ch)
        return "".join(out)

    def _init_schema(self) -> None:
        # sqlite3.executescript has no psycopg2 equivalent, so statements are
        # kept as a list and executed one at a time on both backends.
        for stmt in schema(self.dialect):
            self.execute(stmt)
        self.commit()

    # -- API ---------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> Rows:
        cur = self.con.cursor(**self._cursor_kw)
        cur.execute(self._q(sql), tuple(params))
        rows = Rows()
        if cur.description:
            rows = Rows(Row(r) for r in cur.fetchall())
        cur.close()
        return rows

    def upsert(self, table: str, pk: Sequence[str], values: dict) -> None:
        """`INSERT OR REPLACE` is SQLite-only. Both backends support the ANSI
        `ON CONFLICT … DO UPDATE`, so that is what we emit — one statement,
        both dialects, no branch."""
        cols = list(values)
        ph = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
               f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}"
               if updates else
               f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) "
               f"ON CONFLICT ({', '.join(pk)}) DO NOTHING")
        self.execute(sql, [values[c] for c in cols])

    def commit(self) -> None:
        self.con.commit()

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def preview_sql(dialect: str) -> dict:
    """Render the dialect-sensitive SQL without a live server, so the Postgres
    path is inspectable (and diffable in review) on a machine with no database."""
    class _Fake(Store):
        def __init__(self, d):
            self.dialect = d
    f = _Fake(dialect)
    cols = ["student", "concept", "stability", "last_review", "seen"]
    ph = ", ".join("?" for _ in cols)
    upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in ("student", "concept"))
    return {
        "dialect": dialect,
        "serial_column": [s for s in schema(dialect) if "review_event" in s][0]
                         .split("id ")[1].split(",")[0].strip(),
        "upsert": f.__class__._q(f, f"INSERT INTO mastery ({', '.join(cols)}) VALUES ({ph}) "
                                    f"ON CONFLICT (student, concept) DO UPDATE SET {upd}"),
        "select": f.__class__._q(f, "SELECT * FROM mastery WHERE student=? AND concept=?"),
        "literal_safe": f.__class__._q(f, "SELECT * FROM t WHERE kind='PREREQUISITE_OF' AND x=?"),
    }
