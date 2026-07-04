"""Regression detection — compare eval-score distributions across versions.

A "version" is a `config_version` tag on eval scores (set by offline eval runs). For
each evaluator we summarize the baseline and candidate distributions (n / mean / p50 /
p95 / pass-rate) and flag a regression when the candidate's mean or pass-rate drops
beyond a threshold. This is what catches a prompt/model change that quietly degrades
quality — the platform's headline use case.

Run a demo with:  uv run python -m llm_observatory.regression
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from llm_observatory.logging_config import get_logger
from llm_observatory.models import EvalScore

logger = get_logger(__name__)


@dataclass
class Distribution:
    n: int
    mean: float
    p50: float
    p95: float
    pass_rate: float


@dataclass
class RegressionFinding:
    evaluator: str
    baseline: Distribution
    candidate: Distribution
    delta_mean: float
    delta_pass_rate: float
    regressed: bool


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(q * len(sorted_values)))
    return sorted_values[idx]


def summarize(scores: list[EvalScore]) -> Distribution:
    if not scores:
        return Distribution(0, 0.0, 0.0, 0.0, 0.0)
    values = sorted(s.score for s in scores)
    n = len(scores)
    return Distribution(
        n=n,
        mean=sum(values) / n,
        p50=_percentile(values, 0.5),
        p95=_percentile(values, 0.95),
        pass_rate=sum(1 for s in scores if s.passed) / n,
    )


def _scores(session: Session, config_version: str, evaluator: str) -> list[EvalScore]:
    return list(
        session.scalars(
            select(EvalScore).where(
                EvalScore.config_version == config_version,
                EvalScore.evaluator == evaluator,
            )
        )
    )


def _evaluators(session: Session, config_version: str) -> set[str]:
    return set(
        session.scalars(
            select(EvalScore.evaluator).where(EvalScore.config_version == config_version).distinct()
        )
    )


def compare_versions(
    session: Session,
    baseline_version: str,
    candidate_version: str,
    min_mean_drop: float = 0.05,
    min_pass_drop: float = 0.05,
) -> list[RegressionFinding]:
    """One finding per evaluator seen in either version, ordered worst-regression first."""
    evaluators = _evaluators(session, baseline_version) | _evaluators(session, candidate_version)
    findings = []
    for evaluator in sorted(evaluators):
        baseline = summarize(_scores(session, baseline_version, evaluator))
        candidate = summarize(_scores(session, candidate_version, evaluator))
        delta_mean = candidate.mean - baseline.mean
        delta_pass = candidate.pass_rate - baseline.pass_rate
        # Only flag when both versions have data — a brand-new evaluator can't "regress".
        regressed = (
            baseline.n > 0
            and candidate.n > 0
            and (delta_mean < -min_mean_drop or delta_pass < -min_pass_drop)
        )
        findings.append(
            RegressionFinding(evaluator, baseline, candidate, delta_mean, delta_pass, regressed)
        )
    return sorted(findings, key=lambda f: f.delta_mean)


def main() -> None:
    from pathlib import Path

    from llm_observatory.db import get_engine, init_db, session_factory
    from llm_observatory.offline_eval import Contains, ExactMatch, NonEmpty, load_dataset, run_eval

    engine = get_engine("sqlite:///data/regression_demo.db")
    init_db(engine)
    factory = session_factory(engine)
    dataset = load_dataset(Path("eval/datasets/capitals.jsonl"))
    evaluators = [ExactMatch(), Contains(), NonEmpty()]

    good = {
        "capital of France": "Paris",
        "capital of Japan": "Tokyo",
        "capital of Italy": "Rome",
        "capital of Germany": "Berlin",
        "capital of Australia": "Canberra",
    }
    degraded = {**good, "capital of Japan": "I don't know", "capital of Italy": "I don't know"}

    run_eval(factory, dataset, lambda q: good[q], evaluators, config_version="prompt-v1")
    run_eval(factory, dataset, lambda q: degraded[q], evaluators, config_version="prompt-v2")

    with factory() as session:
        for f in compare_versions(session, "prompt-v1", "prompt-v2"):
            flag = "⚠️ REGRESSED" if f.regressed else "ok"
            logger.info(
                "%-12s mean %.2f -> %.2f (Δ%+.2f)  [%s]",
                f.evaluator,
                f.baseline.mean,
                f.candidate.mean,
                f.delta_mean,
                flag,
            )


if __name__ == "__main__":
    main()
