import pytest

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import EvalScore
from llm_observatory.regression import _percentile, compare_versions, summarize


def test_percentile():
    vals = [0.0, 0.25, 0.5, 0.75, 1.0]
    assert _percentile(vals, 0.5) == 0.5
    assert _percentile(vals, 0.95) == 1.0
    assert _percentile([], 0.5) == 0.0


def _score(config_version, evaluator, score, passed):
    return EvalScore(
        target_type="trace",
        target_id="t",
        evaluator=evaluator,
        mode="offline",
        score=score,
        passed=passed,
        config_version=config_version,
    )


def test_summarize():
    scores = [_score("v", "e", s, s >= 0.5) for s in (0.0, 0.5, 1.0, 1.0)]
    dist = summarize(scores)
    assert dist.n == 4
    assert dist.mean == pytest.approx(0.625)
    assert dist.pass_rate == pytest.approx(0.75)  # three of four >= 0.5


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    f = session_factory(engine)
    with f() as s:
        # baseline: exact_match perfect, len stable
        s.add_all([_score("v1", "exact_match", 1.0, True) for _ in range(5)])
        s.add_all([_score("v1", "length_ok", 1.0, True) for _ in range(5)])
        # candidate: exact_match regressed to 0.6, len stable
        s.add_all(
            [_score("v2", "exact_match", 1.0, True) for _ in range(3)]
            + [_score("v2", "exact_match", 0.0, False) for _ in range(2)]
        )
        s.add_all([_score("v2", "length_ok", 1.0, True) for _ in range(5)])
        # candidate-only evaluator (new) — cannot be a regression
        s.add(_score("v2", "brand_new", 0.2, False))
        s.commit()
    return f


def test_compare_flags_regression(factory):
    with factory() as s:
        findings = {f.evaluator: f for f in compare_versions(s, "v1", "v2")}

        assert findings["exact_match"].regressed is True
        assert findings["exact_match"].delta_mean == pytest.approx(-0.4)
        assert findings["exact_match"].candidate.mean == pytest.approx(0.6)

        assert findings["length_ok"].regressed is False  # unchanged

        # evaluator only present in the candidate: no baseline -> not a regression
        assert findings["brand_new"].regressed is False
        assert findings["brand_new"].baseline.n == 0


def test_findings_ordered_worst_first(factory):
    with factory() as s:
        findings = compare_versions(s, "v1", "v2")
        deltas = [f.delta_mean for f in findings]
        assert deltas == sorted(deltas)  # most-negative (worst) first
