"""Query layer over stored traces — the read side of the platform.

Filter traces by session / model / prompt version / status / time window, paginate,
and fetch a single trace with its spans. The dashboard (Days 29–31) sits on this.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from llm_observatory.models import EvalScore, Trace


@dataclass
class TraceFilter:
    session_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    status: str | None = None
    since: datetime | None = None  # inclusive lower bound on start_time
    until: datetime | None = None  # exclusive upper bound on start_time


def _apply(stmt: Select, f: TraceFilter) -> Select:
    if f.session_id is not None:
        stmt = stmt.where(Trace.session_id == f.session_id)
    if f.model is not None:
        stmt = stmt.where(Trace.model == f.model)
    if f.prompt_version is not None:
        stmt = stmt.where(Trace.prompt_version == f.prompt_version)
    if f.status is not None:
        stmt = stmt.where(Trace.status == f.status)
    if f.since is not None:
        stmt = stmt.where(Trace.start_time >= f.since)
    if f.until is not None:
        stmt = stmt.where(Trace.start_time < f.until)
    return stmt


def list_traces(
    session: Session,
    filter: TraceFilter | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Trace]:
    """Most-recent-first traces matching the filter (paginated)."""
    stmt = _apply(select(Trace), filter or TraceFilter())
    stmt = stmt.order_by(Trace.start_time.desc()).limit(limit).offset(offset)
    return list(session.scalars(stmt))


def count_traces(session: Session, filter: TraceFilter | None = None) -> int:
    """Total traces matching the filter (for pagination)."""
    stmt = _apply(select(func.count()).select_from(Trace), filter or TraceFilter())
    return session.scalar(stmt) or 0


def get_trace(session: Session, trace_id: str) -> Trace | None:
    """A single trace with its spans eagerly loaded, or None."""
    stmt = select(Trace).where(Trace.id == trace_id).options(selectinload(Trace.spans))
    return session.scalars(stmt).first()


def get_scores(session: Session, target_id: str) -> list[EvalScore]:
    """Eval scores attached to a trace or span, oldest first."""
    stmt = select(EvalScore).where(EvalScore.target_id == target_id).order_by(EvalScore.created_at)
    return list(session.scalars(stmt))
