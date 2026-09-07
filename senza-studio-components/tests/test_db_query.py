import sqlite3

import pytest

from senza_studio_components.tools import db_query


@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    conn.execute("INSERT INTO users (name, age) VALUES ('Alice', 30), ('Bob', 25)")
    conn.commit()
    conn.close()
    return str(db_path)


def test_run_returns_columns_and_rows(sample_db):
    result = db_query.run({"db_path": sample_db, "query": "SELECT name, age FROM users ORDER BY name"})
    assert result["columns"] == ["name", "age"]
    assert result["rows"] == [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]


def test_run_rejects_non_select(sample_db):
    with pytest.raises(db_query.DbQueryError, match="SELECT"):
        db_query.run({"db_path": sample_db, "query": "DELETE FROM users"})


def test_run_rejects_multiple_statements(sample_db):
    with pytest.raises(db_query.DbQueryError, match="single SQL statement"):
        db_query.run({"db_path": sample_db, "query": "SELECT 1; DROP TABLE users"})


def test_run_allows_trailing_semicolon(sample_db):
    result = db_query.run({"db_path": sample_db, "query": "SELECT COUNT(*) as n FROM users;"})
    assert result["rows"] == [{"n": 2}]


def test_run_requires_db_path():
    with pytest.raises(db_query.DbQueryError, match="db_path"):
        db_query.run({"query": "SELECT 1"})


def test_run_requires_query(sample_db):
    with pytest.raises(db_query.DbQueryError, match="query"):
        db_query.run({"db_path": sample_db})


def test_run_rejects_empty_query(sample_db):
    with pytest.raises(db_query.DbQueryError, match="empty"):
        db_query.run({"db_path": sample_db, "query": "   "})
