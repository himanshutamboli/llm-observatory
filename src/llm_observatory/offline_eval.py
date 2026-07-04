"""Offline evaluation: run a target over a versioned dataset and persist scores.

Each dataset item is run through the `target` inside a trace (so eval runs show up in
the trace store), then every evaluator scores the output. Scores persist as `eval_score`
rows tagged with `dataset_id`, a per-run `run_id`, and a `config_version` — so runs are
comparable across dataset/evaluator/prompt versions (the input to regression detection).

Run a demo with:  uv run python -m llm_observatory.offline_eval
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from llm_observatory.db import session_factory as make_session_factory
from llm_observatory.logging_config import get_logger
from llm_observatory.models import EvalMode, EvalScore, SpanKind, TargetType
from llm_observatory.sdk import Tracer
from llm_observatory.writer import DBWriter

logger = get_logger(__name__)


@dataclass
class DatasetItem:
    id: str
    input: str
    expected: str | None = None


@dataclass
class Dataset:
    dataset_id: str
    items: list[DatasetItem]


def load_dataset(path: Path) -> Dataset:
    items = []
    for i, line in enumerate(path.read_text().splitlines()):
        if line.strip():
            row = json.loads(line)
            items.append(
                DatasetItem(
                    id=row.get("id", str(i)), input=row["input"], expected=row.get("expected")
                )
            )
    return Dataset(dataset_id=path.stem, items=items)


@dataclass
class EvalResult:
    score: float
    passed: bool
    rationale: str | None = None


class Evaluator(Protocol):
    name: str

    def evaluate(self, item: DatasetItem, output: str) -> EvalResult: ...


class ExactMatch:
    name = "exact_match"

    def evaluate(self, item: DatasetItem, output: str) -> EvalResult:
        if item.expected is None:
            return EvalResult(0.0, False, "no expected value")
        ok = output.strip() == item.expected.strip()
        return EvalResult(1.0 if ok else 0.0, ok)


class Contains:
    name = "contains"

    def evaluate(self, item: DatasetItem, output: str) -> EvalResult:
        if item.expected is None:
            return EvalResult(0.0, False, "no expected value")
        ok = item.expected.strip().lower() in output.lower()
        return EvalResult(1.0 if ok else 0.0, ok)


class NonEmpty:
    name = "non_empty"

    def evaluate(self, item: DatasetItem, output: str) -> EvalResult:
        ok = bool(output.strip())
        return EvalResult(1.0 if ok else 0.0, ok)


@dataclass
class EvalRunResult:
    run_id: str
    dataset_id: str
    config_version: str
    n: int
    mean_score: dict[str, float]
    pass_rate: dict[str, float]


def run_eval(
    session_factory,
    dataset: Dataset,
    target: Callable[[str], str],
    evaluators: list[Evaluator],
    config_version: str,
) -> EvalRunResult:
    run_id = str(uuid.uuid4())
    tracer = Tracer(DBWriter(session_factory))
    scores: list[EvalScore] = []
    by_evaluator_score: dict[str, list[float]] = defaultdict(list)
    by_evaluator_pass: dict[str, list[bool]] = defaultdict(list)

    for item in dataset.items:
        with tracer.trace("eval_item", session_id=run_id, prompt_version=config_version) as t:
            with t.span("target", kind=SpanKind.LLM.value, input=item.input) as span:
                output = target(item.input)
                span.set_output(output)
        for evaluator in evaluators:
            result = evaluator.evaluate(item, output)
            scores.append(
                EvalScore(
                    target_type=TargetType.TRACE.value,
                    target_id=t.record.id,
                    evaluator=evaluator.name,
                    mode=EvalMode.OFFLINE.value,
                    score=result.score,
                    passed=result.passed,
                    rationale=result.rationale,
                    dataset_id=dataset.dataset_id,
                    run_id=run_id,
                    config_version=config_version,
                )
            )
            by_evaluator_score[evaluator.name].append(result.score)
            by_evaluator_pass[evaluator.name].append(result.passed)

    with session_factory() as session:
        session.add_all(scores)
        session.commit()

    return EvalRunResult(
        run_id=run_id,
        dataset_id=dataset.dataset_id,
        config_version=config_version,
        n=len(dataset.items),
        mean_score={k: sum(v) / len(v) for k, v in by_evaluator_score.items()},
        pass_rate={k: sum(v) / len(v) for k, v in by_evaluator_pass.items()},
    )


def main() -> None:
    from llm_observatory.db import get_engine, init_db

    engine = get_engine()
    init_db(engine)
    factory = make_session_factory(engine)

    dataset = load_dataset(Path("eval/datasets/capitals.jsonl"))
    answers = {
        "capital of France": "Paris",
        "capital of Japan": "Tokyo",
        "capital of Italy": "Rome",
        "capital of Germany": "Berlin",
    }
    target = lambda q: answers.get(q, "I don't know")  # noqa: E731 (misses Australia on purpose)

    result = run_eval(
        factory, dataset, target, [ExactMatch(), Contains(), NonEmpty()], config_version="eval-v1"
    )
    logger.info(
        "run %s dataset=%s n=%d mean_score=%s pass_rate=%s",
        result.run_id[:8],
        result.dataset_id,
        result.n,
        {k: round(v, 2) for k, v in result.mean_score.items()},
        {k: round(v, 2) for k, v in result.pass_rate.items()},
    )


if __name__ == "__main__":
    main()
