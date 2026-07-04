import sqlite3

from alembic import command
from alembic.config import Config


def test_migration_creates_all_tables(tmp_path, monkeypatch):
    """`alembic upgrade head` builds the full schema on a fresh database."""
    db = tmp_path / "migrated.db"
    monkeypatch.setenv("LLMOBS_DATABASE_URL", f"sqlite:///{db}")

    command.upgrade(Config("alembic.ini"), "head")

    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"traces", "spans", "eval_scores", "alembic_version"} <= tables


def test_migration_is_reversible(tmp_path, monkeypatch):
    db = tmp_path / "roundtrip.db"
    monkeypatch.setenv("LLMOBS_DATABASE_URL", f"sqlite:///{db}")
    cfg = Config("alembic.ini")

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "traces" not in tables and "spans" not in tables
