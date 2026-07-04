"""Data model for the observability platform: traces, spans, and eval scores.

A **trace** is one logical operation (e.g. a RAG answer). It contains a tree of
**spans** (llm / retrieval / tool / function calls) capturing i/o, tokens, cost,
and latency. **Eval scores** attach to a trace or span, from offline dataset runs
or online sampling.

Column types are chosen to be portable across SQLite (dev) and Postgres (prod):
string UUIDs, generic JSON, no dialect-specific types.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SpanKind(StrEnum):
    LLM = "llm"
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    FUNCTION = "function"


class TraceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class EvalMode(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"


class TargetType(StrEnum):
    TRACE = "trace"
    SPAN = "span"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    session_id: Mapped[str | None] = mapped_column(String(255), index=True)
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=TraceStatus.OK.value)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=_now)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    spans: Mapped[list["Span"]] = relationship(back_populates="trace", cascade="all, delete-orphan")


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(ForeignKey("spans.id"))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), default=SpanKind.LLM.value)
    input: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=TraceStatus.OK.value)
    error: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=_now)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)

    trace: Mapped["Trace"] = relationship(back_populates="spans")


class EvalScore(Base):
    __tablename__ = "eval_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Polymorphic target (trace or span) — kept FK-free so a score can point at either.
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    evaluator: Mapped[str] = mapped_column(String(128), index=True)
    mode: Mapped[str] = mapped_column(String(16), default=EvalMode.OFFLINE.value)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column()
    rationale: Mapped[str | None] = mapped_column(Text)
    dataset_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    config_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
