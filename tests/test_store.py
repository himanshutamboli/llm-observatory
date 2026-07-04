from datetime import UTC, datetime, timedelta

import pytest

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import Span, Trace
from llm_observatory.store import (
    TraceFilter,
    count_traces,
    get_scores,
    get_trace,
    list_traces,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    f = session_factory(engine)
    with f() as s:
        # 5 traces, increasing start_time, mixed session/model/status
        s.add_all(
            [
                Trace(
                    name="t0",
                    session_id="a",
                    model="claude-opus-4-8",
                    status="ok",
                    start_time=BASE + timedelta(minutes=0),
                ),
                Trace(
                    name="t1",
                    session_id="a",
                    model="claude-sonnet-5",
                    status="ok",
                    start_time=BASE + timedelta(minutes=1),
                ),
                Trace(
                    name="t2",
                    session_id="b",
                    model="claude-opus-4-8",
                    status="error",
                    start_time=BASE + timedelta(minutes=2),
                ),
                Trace(
                    name="t3",
                    session_id="b",
                    model="claude-opus-4-8",
                    status="ok",
                    start_time=BASE + timedelta(minutes=3),
                ),
                Trace(
                    name="t4",
                    session_id="a",
                    model="claude-opus-4-8",
                    status="ok",
                    start_time=BASE + timedelta(minutes=4),
                ),
            ]
        )
        s.commit()
    return f


def test_list_all_most_recent_first(factory):
    with factory() as s:
        traces = list_traces(s)
        assert [t.name for t in traces] == ["t4", "t3", "t2", "t1", "t0"]


def test_filter_by_session_and_model(factory):
    with factory() as s:
        assert {t.name for t in list_traces(s, TraceFilter(session_id="a"))} == {"t0", "t1", "t4"}
        assert {t.name for t in list_traces(s, TraceFilter(model="claude-opus-4-8"))} == {
            "t0",
            "t2",
            "t3",
            "t4",
        }
        assert {t.name for t in list_traces(s, TraceFilter(status="error"))} == {"t2"}


def test_time_window(factory):
    with factory() as s:
        f = TraceFilter(since=BASE + timedelta(minutes=1), until=BASE + timedelta(minutes=3))
        assert {t.name for t in list_traces(s, f)} == {"t1", "t2"}


def test_pagination_and_count(factory):
    with factory() as s:
        assert count_traces(s) == 5
        assert count_traces(s, TraceFilter(session_id="a")) == 3
        page = list_traces(s, limit=2, offset=2)
        assert [t.name for t in page] == ["t2", "t1"]


def test_get_trace_with_spans_and_missing(factory):
    with factory() as s:
        trace = list_traces(s, TraceFilter(session_id="b"))[0]
        s.add(Span(trace_id=trace.id, name="generate", kind="llm"))
        s.commit()
        tid = trace.id

    with factory() as s:
        fetched = get_trace(s, tid)
        assert fetched is not None
        assert [sp.name for sp in fetched.spans] == ["generate"]
        assert get_trace(s, "does-not-exist") is None
        assert get_scores(s, tid) == []
