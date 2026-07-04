from pathlib import Path

import pytest
from sqlalchemy import func, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import EvalScore, Trace
from llm_observatory.offline_eval import (
    Contains,
    Dataset,
    DatasetItem,
    ExactMatch,
    NonEmpty,
    load_dataset,
    run_eval,
)


def test_evaluators():
    item = DatasetItem(id="1", input="capital of France", expected="Paris")
    assert ExactMatch().evaluate(item, "Paris").passed
    assert not ExactMatch().evaluate(item, "paris city").passed
    assert Contains().evaluate(item, "The capital is Paris.").passed
    assert NonEmpty().evaluate(item, "x").passed
    assert not NonEmpty().evaluate(item, "  ").passed


def test_load_dataset(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"input": "a", "expected": "b"}\n{"input": "c"}\n')
    ds = load_dataset(p)
    assert ds.dataset_id == "d"
    assert [i.input for i in ds.items] == ["a", "c"]
    assert ds.items[1].expected is None


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    return session_factory(engine)


def test_run_eval_persists_scores_and_traces(factory):
    dataset = Dataset(
        "caps",
        [
            DatasetItem("1", "capital of France", "Paris"),
            DatasetItem("2", "capital of Japan", "Tokyo"),
        ],
    )
    answers = {"capital of France": "Paris"}  # Japan is wrong on purpose
    target = lambda q: answers.get(q, "I don't know")  # noqa: E731
    evaluators = [ExactMatch(), NonEmpty()]

    result = run_eval(factory, dataset, target, evaluators, config_version="eval-v1")

    assert result.n == 2
    assert result.mean_score["exact_match"] == 0.5  # 1 of 2 correct
    assert result.pass_rate["non_empty"] == 1.0

    with factory() as s:
        # one trace per item, one score per (item, evaluator)
        assert s.scalar(select(func.count()).select_from(Trace)) == 2
        scores = s.scalars(select(EvalScore)).all()
        assert len(scores) == 4
        assert all(sc.dataset_id == "caps" for sc in scores)
        assert all(sc.run_id == result.run_id for sc in scores)
        assert all(sc.config_version == "eval-v1" for sc in scores)
        assert all(sc.mode == "offline" for sc in scores)
        # every score targets a real trace
        trace_ids = {t.id for t in s.scalars(select(Trace)).all()}
        assert all(sc.target_id in trace_ids for sc in scores)


def test_ships_a_committed_dataset():
    ds = load_dataset(Path("eval/datasets/capitals.jsonl"))
    assert ds.dataset_id == "capitals"
    assert len(ds.items) == 5
