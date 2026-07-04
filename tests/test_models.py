from datetime import datetime

from sqlalchemy import Engine, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import (
    EvalMode,
    EvalScore,
    Span,
    SpanKind,
    TargetType,
    Trace,
)


def _engine(tmp_path) -> Engine:
    # File-based sqlite so multiple sessions share one database (in-memory would not).
    engine = get_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return engine


def test_trace_with_spans_and_eval_score(tmp_path):
    Session = session_factory(_engine(tmp_path))
    with Session() as s:
        trace = Trace(name="rag_answer", model="claude-opus-4-8", prompt_version="v1")
        trace.spans = [
            Span(name="retrieve", kind=SpanKind.RETRIEVAL.value),
            Span(name="generate", kind=SpanKind.LLM.value, prompt_tokens=100, completion_tokens=50),
        ]
        s.add(trace)
        s.commit()
        trace_id = trace.id

    with Session() as s:
        trace = s.get(Trace, trace_id)
        assert len(trace.spans) == 2
        assert {sp.kind for sp in trace.spans} == {"retrieval", "llm"}
        s.add(
            EvalScore(
                target_type=TargetType.TRACE.value,
                target_id=trace_id,
                evaluator="faithfulness",
                mode=EvalMode.OFFLINE.value,
                score=0.9,
                passed=True,
            )
        )
        s.commit()

    with Session() as s:
        scores = s.scalars(select(EvalScore).where(EvalScore.target_id == trace_id)).all()
        assert len(scores) == 1
        assert scores[0].score == 0.9 and scores[0].passed is True


def test_cascade_delete_removes_spans(tmp_path):
    Session = session_factory(_engine(tmp_path))
    with Session() as s:
        trace = Trace(name="x", spans=[Span(name="a"), Span(name="b")])
        s.add(trace)
        s.commit()
        trace_id = trace.id

    with Session() as s:
        s.delete(s.get(Trace, trace_id))
        s.commit()

    with Session() as s:
        assert s.scalars(select(Span)).all() == []


def test_defaults(tmp_path):
    Session = session_factory(_engine(tmp_path))
    with Session() as s:
        trace = Trace(name="d")
        s.add(trace)
        s.commit()
        assert len(trace.id) == 36  # uuid
        assert trace.status == "ok"
        assert trace.total_tokens == 0 and trace.total_cost_usd == 0.0
        assert trace.attributes == {}
        assert isinstance(trace.start_time, datetime)
