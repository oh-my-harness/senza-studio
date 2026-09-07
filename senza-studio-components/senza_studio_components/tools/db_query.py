"""db_query — run a read-only SQL query against a SQLite database file.

Deliberately read-only: this tool is meant to let a workflow step look up
data, not mutate it. Non-SELECT statements (and multi-statement input) are
rejected rather than executed.
"""
from __future__ import annotations

import sqlite3


class DbQueryError(ValueError):
    pass


def _validate_select_only(query: str) -> str:
    stripped = query.strip()
    if not stripped:
        raise DbQueryError("query is empty")
    # Reject multiple statements (e.g. "SELECT 1; DROP TABLE x") — a
    # trailing single semicolon is fine, anything after it is not.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        raise DbQueryError("only a single SQL statement is allowed")
    if not body.lstrip().upper().startswith("SELECT"):
        raise DbQueryError("only SELECT queries are allowed (read-only tool)")
    return body


def run(args: dict) -> dict:
    """args: {"db_path": str, "query": str}. Returns {"columns": [...], "rows": [...]}."""
    db_path = args.get("db_path")
    query = args.get("query")
    if not db_path:
        raise DbQueryError("db_path is required")
    if not query:
        raise DbQueryError("query is required")

    statement = _validate_select_only(query)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(statement)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()

    return {"columns": columns, "rows": rows}
