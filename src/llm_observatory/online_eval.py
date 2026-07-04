"""Online evaluation: sample live traces and score them asynchronously.

Unlike offline eval (dataset with expected answers), online eval scores real traffic
with label-free, trace-level evaluators — no-error, latency budget, cost budget. It:

* **samples** deterministically by trace-id hash (consistent across runs, tunable rate),
* **dedups** so a trace isn't scored twice by the same evaluator,
* runs **off the hot path** (a scheduled/background job; `sample_and_score_async` offloads
  it to a thread), persisting `eval_score` rows with `mode="online"`.

Run a demo with:  uv run python -m llm_observatory.online_eval
"""

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from llm_observatory.logging_config import get_logger
from llm_observatory.models import EvalMode, EvalScore, TargetType, Trace
from llm_observatory.offline_eval import EvalResult
from llm_observatory.store import TraceFilter, list_traces

logger = get_logger(__name__)


class TraceEvaluator(Protocol):
    name: str

    def evaluate(self, trace: Trace) -> EvalResult: ...


class NoError:
    name = "no_error"

    def evaluate(self, trace: Trace) -> EvalResult:
        ok = trace.status == "ok"
        return EvalResult(1.0 if ok else 0.0, ok)


class LatencyBudget:
    name = "latency_budget"

    def __init__(self, max_ms: int) -> None:
        self.max_ms = max_ms

    def evaluate(self, trace: Trace) -> EvalResult:
        latency = trace.latency_ms or 0
        ok = latency <= self.max_ms
        return EvalResult(1.0 if ok else 0.0, ok, f"{latency}ms vs budget {self.max_ms}ms")


class CostBudget:
    name = "cost_budget"

    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd

    def evaluate(self, trace: Trace) -> EvalResult:
        ok = trace.total_cost_usd <= self.max_usd
        return EvalResult(1.0 if ok else 0.0, ok, f"${trace.total_cost_usd:.4f} vs ${self.max_usd}")


def is_sampled(trace_id: str, rate: float) -> bool:
    """Deterministic per-trace sampling: same id + rate -> same decision."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    bucket = int(hashlib.sha256(trace_id.encode()).hexdigest()[:8], 16) % 10_000
    return bucket / 10_000 < rate


@dataclass
class OnlineSummary:
    n_candidates: int
    n_sampled: int
    n_scored: int
    mean_score: dict[str, float]
    pass_rate: dict[str, float]


def sample_and_score(
    session_factory,
    evaluators: list[TraceEvaluator],
    sample_rate: float = 0.1,
    filter: TraceFilter | None = None,
    limit: int = 10_000,
) -> OnlineSummary:
    with session_factory() as session:
        candidates = list_traces(session, filter, limit=limit)

        # Existing (trace, evaluator) online pairs, so we never double-score.
        existing = {
            (row.target_id, row.evaluator)
            for row in session.execute(
                select(EvalScore.target_id, EvalScore.evaluator).where(
                    EvalScore.mode == EvalMode.ONLINE.value
                )
            )
        }

        new_scores: list[EvalScore] = []
        sampled: set[str] = set()
        by_score: dict[str, list[float]] = defaultdict(list)
        by_pass: dict[str, list[bool]] = defaultdict(list)

        for trace in candidates:
            if not is_sampled(trace.id, sample_rate):
                continue
            sampled.add(trace.id)
            for evaluator in evaluators:
                if (trace.id, evaluator.name) in existing:
                    continue
                result = evaluator.evaluate(trace)
                new_scores.append(
                    EvalScore(
                        target_type=TargetType.TRACE.value,
                        target_id=trace.id,
                        evaluator=evaluator.name,
                        mode=EvalMode.ONLINE.value,
                        score=result.score,
                        passed=result.passed,
                        rationale=result.rationale,
                    )
                )
                by_score[evaluator.name].append(result.score)
                by_pass[evaluator.name].append(result.passed)

        session.add_all(new_scores)
        session.commit()

    return OnlineSummary(
        n_candidates=len(candidates),
        n_sampled=len(sampled),
        n_scored=len(new_scores),
        mean_score={k: sum(v) / len(v) for k, v in by_score.items()},
        pass_rate={k: sum(v) / len(v) for k, v in by_pass.items()},
    )


async def sample_and_score_async(*args, **kwargs) -> OnlineSummary:
    """Run the sampler off the event loop (models a background scoring job)."""
    return await asyncio.to_thread(sample_and_score, *args, **kwargs)


def main() -> None:
    from llm_observatory.db import get_engine, init_db, session_factory

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)

    summary = sample_and_score(
        factory,
        [NoError(), LatencyBudget(2000), CostBudget(0.05)],
        sample_rate=1.0,  # score everything for the demo
    )
    logger.info(
        "candidates=%d sampled=%d scored=%d pass_rate=%s",
        summary.n_candidates,
        summary.n_sampled,
        summary.n_scored,
        {k: round(v, 2) for k, v in summary.pass_rate.items()},
    )


if __name__ == "__main__":
    main()
