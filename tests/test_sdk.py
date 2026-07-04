import pytest
from sqlalchemy import select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import Trace
from llm_observatory.sdk import Tracer, estimate_cost
from llm_observatory.writer import DBWriter, MemoryWriter


def test_estimate_cost():
    # 1M input + 1M output on Opus 4.8 = $5 + $25
    assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0
    assert estimate_cost("unknown-model", 1_000_000, 0) == 0.0


def test_trace_rolls_up_spans():
    writer = MemoryWriter()
    tracer = Tracer(writer)
    with tracer.trace("rag_answer", model="claude-opus-4-8") as t:
        with t.span("retrieve", kind="retrieval", input="q") as s:
            s.set_output("chunks")
        with t.span("generate", kind="llm", model="claude-opus-4-8") as s:
            s.set_output("answer")
            s.set_usage(prompt_tokens=1200, completion_tokens=180)

    (rec,) = writer.traces
    assert rec.status == "ok"
    assert len(rec.spans) == 2
    assert rec.total_tokens == 1380
    assert rec.total_cost_usd == pytest.approx(0.0105)  # 1200*5/1e6 + 180*25/1e6
    assert rec.latency_ms is not None
    assert rec.spans[0].kind == "retrieval" and rec.spans[1].kind == "llm"


def test_exception_marks_error_and_reraises():
    writer = MemoryWriter()
    tracer = Tracer(writer)
    with pytest.raises(ValueError):  # noqa: PT012
        with tracer.trace("t") as t:
            with t.span("s") as s:  # noqa: F841
                raise ValueError("boom")

    (rec,) = writer.traces  # trace was still persisted despite the error
    assert rec.status == "error"
    assert rec.spans[0].status == "error"
    assert rec.spans[0].error == "boom"


def test_observe_decorator_captures_output():
    writer = MemoryWriter()
    tracer = Tracer(writer)

    @tracer.observe(name="greet")
    def greet(who: str) -> str:
        return f"hi {who}"

    assert greet("world") == "hi world"
    (rec,) = writer.traces
    assert rec.name == "greet"
    assert rec.spans[0].output == "hi world"


def test_db_writer_persists_trace_and_spans(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    factory = session_factory(engine)

    tracer = Tracer(DBWriter(factory))
    with tracer.trace("rag_answer", model="claude-opus-4-8") as t:
        with t.span("generate", kind="llm", model="claude-opus-4-8") as s:
            s.set_usage(prompt_tokens=100, completion_tokens=50)

    with factory() as session:
        trace = session.scalars(select(Trace)).one()
        assert trace.name == "rag_answer"
        assert len(trace.spans) == 1
        assert trace.total_tokens == 150
        assert trace.total_cost_usd == pytest.approx(0.00175)
