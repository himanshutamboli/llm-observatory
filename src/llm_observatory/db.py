"""Engine + session factory. SQLite for dev; point LLMOBS_DATABASE_URL at Postgres for prod."""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from llm_observatory.models import Base

DEFAULT_URL = "sqlite:///data/observatory.db"


def database_url() -> str:
    return os.environ.get("LLMOBS_DATABASE_URL", DEFAULT_URL)


def get_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all tables directly (used for tests / quick local setup).

    Production uses Alembic migrations (`alembic upgrade head`), not this.
    """
    Base.metadata.create_all(engine)
