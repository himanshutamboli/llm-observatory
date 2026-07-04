from datetime import UTC, datetime

import pytest

from llm_observatory.analytics import cost_latency_series, pass_rate_series
from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import EvalScore, Trace

DAY1 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def _score(target_id, ok):
    return EvalScore(
        target_type="trace",
        target_id=target_id,
        evaluator="no_error",
        mode="online",
        score=1.0 if ok else 0.0,
        passed=ok,
    )


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    f = session_factory(engine)
    with f() as s:
        t1 = Trace(
            id="t1",
            name="x",
            status="ok",
            start_time=DAY1,
            latency_ms=100,
            total_tokens=100,
            total_cost_usd=0.01,
        )
        t2 = Trace(
            id="t2",
            name="x",
            status="ok",
            start_time=DAY1,
            latency_ms=300,
            total_tokens=200,
            total_cost_usd=0.02,
        )
        t3 = Trace(
            id="t3",
            name="x",
            status="error",
            start_time=DAY2,
            latency_ms=900,
            total_tokens=300,
            total_cost_usd=0.03,
        )
        s.add_all([t1, t2, t3, _score("t1", True), _score("t2", True), _score("t3", False)])
        s.commit()
    return f


def test_cost_latency_series(factory):
    with factory() as s:
        series = cost_latency_series(s)
    assert [r["period"] for r in series] == ["2026-01-01", "2026-01-02"]
    day1, day2 = series
    assert day1["n"] == 2
    assert day1["avg_latency_ms"] == 200.0  # (100 + 300) / 2
    assert day1["total_cost_usd"] == pytest.approx(0.03)
    assert day2["n"] == 1 and day2["avg_latency_ms"] == 900.0


def test_pass_rate_series_by_trace_time(factory):
    with factory() as s:
        series = pass_rate_series(s, "no_error")
    by_period = {r["period"]: r["pass_rate"] for r in series}
    assert by_period["2026-01-01"] == 1.0  # both ok
    assert by_period["2026-01-02"] == 0.0  # errored
