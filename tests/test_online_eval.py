import asyncio

import pytest
from sqlalchemy import func, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import EvalScore, Trace
from llm_observatory.online_eval import (
    CostBudget,
    LatencyBudget,
    NoError,
    is_sampled,
    sample_and_score,
    sample_and_score_async,
)


def test_is_sampled_bounds_and_determinism():
    assert is_sampled("x", 1.0) is True
    assert is_sampled("x", 0.0) is False
    assert is_sampled("abc", 0.5) == is_sampled("abc", 0.5)  # deterministic


def test_is_sampled_fraction_is_approximately_rate():
    ids = [f"trace-{i}" for i in range(2000)]
    sampled = sum(is_sampled(i, 0.3) for i in ids)
    assert 400 < sampled < 800  # ~600, loose bound


def test_trace_evaluators():
    ok = Trace(name="a", status="ok", latency_ms=100, total_cost_usd=0.01)
    bad = Trace(name="b", status="error", latency_ms=5000, total_cost_usd=1.0)
    assert NoError().evaluate(ok).passed and not NoError().evaluate(bad).passed
    assert LatencyBudget(500).evaluate(ok).passed and not LatencyBudget(500).evaluate(bad).passed
    assert CostBudget(0.05).evaluate(ok).passed and not CostBudget(0.05).evaluate(bad).passed


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    f = session_factory(engine)
    with f() as s:
        s.add_all(
            [
                Trace(name="ok", status="ok", latency_ms=100, total_cost_usd=0.01),
                Trace(name="slow", status="ok", latency_ms=9000, total_cost_usd=0.01),
                Trace(name="err", status="error", latency_ms=100, total_cost_usd=0.01),
            ]
        )
        s.commit()
    return f


def test_sample_and_score_persists_online_scores(factory):
    summary = sample_and_score(factory, [NoError(), LatencyBudget(500)], sample_rate=1.0)
    assert summary.n_candidates == 3
    assert summary.n_sampled == 3
    assert summary.n_scored == 6  # 3 traces * 2 evaluators
    assert summary.pass_rate["no_error"] == pytest.approx(2 / 3)  # one error
    assert summary.pass_rate["latency_budget"] == pytest.approx(2 / 3)  # one slow

    with factory() as s:
        scores = s.scalars(select(EvalScore)).all()
        assert len(scores) == 6
        assert all(sc.mode == "online" for sc in scores)


def test_sampler_dedups_on_rerun(factory):
    first = sample_and_score(factory, [NoError()], sample_rate=1.0)
    assert first.n_scored == 3
    second = sample_and_score(factory, [NoError()], sample_rate=1.0)
    assert second.n_scored == 0  # already scored
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(EvalScore)) == 3


def test_async_wrapper(factory):
    summary = asyncio.run(sample_and_score_async(factory, [NoError()], sample_rate=1.0))
    assert summary.n_scored == 3
