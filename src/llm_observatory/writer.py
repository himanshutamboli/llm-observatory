"""Writers persist a completed trace. The SDK captures; the writer stores.

`MemoryWriter` keeps traces in a list (tests). `DBWriter` maps the captured records
onto the ORM models and commits. Writers read the record via attributes only, so the
SDK doesn't depend on the storage layer.
"""

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session, sessionmaker

from llm_observatory.models import Span, Trace


@runtime_checkable
class Writer(Protocol):
    def write(self, trace) -> str: ...


class MemoryWriter:
    """Collects traces in memory — for tests and dry runs."""

    def __init__(self) -> None:
        self.traces: list = []

    def write(self, trace) -> str:
        self.traces.append(trace)
        return trace.id


class DBWriter:
    """Persists a captured trace (and its spans) into the database."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def write(self, trace) -> str:
        with self._session_factory() as session:
            row = Trace(
                id=trace.id,
                name=trace.name,
                session_id=trace.session_id,
                model=trace.model,
                prompt_version=trace.prompt_version,
                status=trace.status,
                start_time=trace.start_time,
                end_time=trace.end_time,
                latency_ms=trace.latency_ms,
                total_tokens=trace.total_tokens,
                total_cost_usd=trace.total_cost_usd,
            )
            for s in trace.spans:
                row.spans.append(
                    Span(
                        id=s.id,
                        name=s.name,
                        kind=s.kind,
                        input=s.input,
                        output=s.output,
                        model=s.model,
                        prompt_tokens=s.prompt_tokens,
                        completion_tokens=s.completion_tokens,
                        cost_usd=s.cost_usd,
                        status=s.status,
                        error=s.error,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        latency_ms=s.latency_ms,
                    )
                )
            session.add(row)
            session.commit()
            return trace.id
