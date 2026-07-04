from sqlalchemy import func, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.demo import CORPUS, observed_answer, run_demo
from llm_observatory.models import Trace
from llm_observatory.sdk import Tracer
from llm_observatory.writer import MemoryWriter


def test_observed_answer_traces_and_answers():
    writer = MemoryWriter()
    tracer = Tracer(writer)

    answer = observed_answer(tracer, "how do I reset password")
    assert answer == CORPUS["reset password"]

    (trace,) = writer.traces
    assert trace.name == "support_answer"
    assert [s.kind for s in trace.spans] == ["retrieval", "llm"]
    assert trace.spans[1].prompt_tokens > 0  # usage captured


def test_observed_answer_handles_unknown_question():
    tracer = Tracer(MemoryWriter())
    answer = observed_answer(tracer, "teach me to fly a plane")
    assert "don't have information" in answer


def test_run_demo_populates_scenario(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    factory = session_factory(engine)

    summary = run_demo(factory, seed_n=20, queries=["how do I reset password", "teach me to fly"])

    assert summary["historical_traces"] == 20
    assert summary["live_traces"] == 2
    assert summary["scores_written"] == 6  # 2 live traces * 3 evaluators (historical deduped)
    assert isinstance(summary["alerts_fired"], list)

    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Trace)) == 22
