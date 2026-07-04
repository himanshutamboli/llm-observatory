"""Instrumentation SDK: trace/span context managers + an @observe decorator.

Usage:

    tracer = Tracer(DBWriter(session_factory))
    with tracer.trace("rag_answer", model="claude-opus-4-8") as t:
        with t.span("retrieve", kind="retrieval", input=query) as s:
            s.set_output(str(chunks))
        with t.span("generate", kind="llm", model="claude-opus-4-8") as s:
            s.set_output(answer)
            s.set_usage(prompt_tokens=1200, completion_tokens=180)  # cost derived from model

On trace exit, totals are rolled up from the spans and the trace is handed to the writer.
Exceptions mark the span/trace status "error" and are re-raised.

Run a demo with:  uv run python -m llm_observatory.sdk
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps

from llm_observatory.logging_config import get_logger
from llm_observatory.models import SpanKind
from llm_observatory.writer import Writer

logger = get_logger(__name__)

# Input/output $ per 1M tokens (see the claude-api pricing table).
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    if model not in PRICES:
        return 0.0
    price_in, price_out = PRICES[model]
    return prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SpanRecord:
    name: str
    trace_id: str
    kind: str = SpanKind.LLM.value
    id: str = field(default_factory=_uuid)
    input: str | None = None
    output: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    status: str = "ok"
    error: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    latency_ms: int | None = None


@dataclass
class TraceRecord:
    name: str
    id: str = field(default_factory=_uuid)
    session_id: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    status: str = "ok"
    start_time: datetime | None = None
    end_time: datetime | None = None
    latency_ms: int | None = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    spans: list[SpanRecord] = field(default_factory=list)


class _SpanCtx:
    def __init__(self, record: SpanRecord) -> None:
        self.record = record
        self._t0 = 0.0

    def __enter__(self) -> "_SpanCtx":
        self._t0 = time.perf_counter()
        self.record.start_time = _now()
        return self

    def set_output(self, text: str) -> None:
        self.record.output = text

    def set_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model: str | None = None,
        cost_usd: float | None = None,
    ) -> None:
        r = self.record
        r.prompt_tokens = prompt_tokens
        r.completion_tokens = completion_tokens
        r.model = model or r.model
        r.cost_usd = (
            cost_usd
            if cost_usd is not None
            else estimate_cost(r.model, prompt_tokens, completion_tokens)
        )

    def __exit__(self, exc_type, exc, tb) -> bool:
        r = self.record
        r.end_time = _now()
        r.latency_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc_type is not None:
            r.status = "error"
            r.error = str(exc)
        return False  # never suppress


class _TraceCtx:
    def __init__(self, record: TraceRecord, writer: Writer) -> None:
        self.record = record
        self._writer = writer
        self._t0 = 0.0

    def __enter__(self) -> "_TraceCtx":
        self._t0 = time.perf_counter()
        self.record.start_time = _now()
        return self

    def span(
        self,
        name: str,
        kind: str = SpanKind.LLM.value,
        input: str | None = None,
        model: str | None = None,
    ) -> _SpanCtx:
        record = SpanRecord(
            name=name, trace_id=self.record.id, kind=str(kind), input=input, model=model
        )
        self.record.spans.append(record)
        return _SpanCtx(record)

    def __exit__(self, exc_type, exc, tb) -> bool:
        r = self.record
        r.end_time = _now()
        r.latency_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc_type is not None:
            r.status = "error"
        r.total_tokens = sum(s.prompt_tokens + s.completion_tokens for s in r.spans)
        r.total_cost_usd = sum(s.cost_usd for s in r.spans)
        self._writer.write(r)
        return False  # persist, then re-raise


class Tracer:
    def __init__(self, writer: Writer) -> None:
        self.writer = writer

    def trace(
        self,
        name: str,
        session_id: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> _TraceCtx:
        record = TraceRecord(
            name=name, session_id=session_id, model=model, prompt_version=prompt_version
        )
        return _TraceCtx(record, self.writer)

    def observe(self, name: str | None = None, kind: str = SpanKind.FUNCTION.value):
        """Decorator: trace a whole function as one trace+span, capturing its output."""

        def decorator(fn):
            @wraps(fn)
            def wrapper(*args, **kwargs):
                trace_name = name or fn.__name__
                with self.trace(trace_name) as t, t.span(trace_name, kind=kind) as s:
                    result = fn(*args, **kwargs)
                    s.set_output(str(result))
                    return result

            return wrapper

        return decorator


def main() -> None:
    from sqlalchemy import select

    from llm_observatory.db import get_engine, init_db, session_factory
    from llm_observatory.models import Trace
    from llm_observatory.writer import DBWriter

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)

    tracer = Tracer(DBWriter(factory))
    with tracer.trace(
        "rag_answer", model="claude-opus-4-8", prompt_version="v1", session_id="demo"
    ) as t:
        with t.span("retrieve", kind=SpanKind.RETRIEVAL.value, input="what is overfitting?") as s:
            s.set_output("[3 retrieved chunks]")
        with t.span("generate", kind=SpanKind.LLM.value, model="claude-opus-4-8") as s:
            s.set_output("Overfitting is when a model memorizes noise ...")
            s.set_usage(prompt_tokens=1200, completion_tokens=180)

    with factory() as session:
        trace = session.scalars(select(Trace).order_by(Trace.start_time.desc())).first()
        logger.info(
            "Traced %r: %d spans, %d tokens, $%.4f, %dms",
            trace.name,
            len(trace.spans),
            trace.total_tokens,
            trace.total_cost_usd,
            trace.latency_ms,
        )


if __name__ == "__main__":
    main()
