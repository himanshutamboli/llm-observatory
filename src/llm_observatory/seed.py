"""Seed a realistic demo scenario: traces spread over time with a quality regression.

Traces are backdated across a window; the recent third switches to prompt-v2 and
degrades (higher latency, more errors) — so the trends view and regression/alerting
have a real signal to show. Deterministic (seeded RNG). Direct ORM inserts (with
matching online eval scores) so timestamps and scores can be controlled.

Run with:  uv run python -m llm_observatory.seed
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

from llm_observatory.logging_config import get_logger
from llm_observatory.models import EvalMode, EvalScore, Span, SpanKind, TargetType, Trace
from llm_observatory.sdk import estimate_cost

logger = get_logger(__name__)

MODELS = ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]
LATENCY_BUDGET_MS = 2000
COST_BUDGET_USD = 0.05


def _score(
    target_id: str, evaluator: str, ok: bool, rationale: str, created_at: datetime
) -> EvalScore:
    return EvalScore(
        target_type=TargetType.TRACE.value,
        target_id=target_id,
        evaluator=evaluator,
        mode=EvalMode.ONLINE.value,
        score=1.0 if ok else 0.0,
        passed=ok,
        rationale=rationale,
        created_at=created_at,
    )


def seed_demo(session_factory, n: int = 120, days: int = 14, seed: int = 42) -> int:
    """Create n backdated traces (with a regression in the recent window) + eval scores."""
    rng = random.Random(seed)
    now = datetime.now(UTC)
    objects: list = []

    for i in range(n):
        frac = i / (n - 1)  # 0 = oldest, 1 = newest
        start = now - timedelta(days=days * (1 - frac))
        regressed = frac > 0.66  # recent third degrades

        model = rng.choice(MODELS)
        prompt_version = "prompt-v2" if regressed else "prompt-v1"
        latency = rng.randint(200, 800) + (rng.randint(800, 2600) if regressed else 0)
        errored = rng.random() < (0.25 if regressed else 0.04)
        prompt_tokens = rng.randint(500, 2000)
        completion_tokens = rng.randint(50, 400)
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        status = "error" if errored else "ok"

        tid = str(uuid.uuid4())
        objects.append(
            Trace(
                id=tid,
                name="rag_answer",
                model=model,
                prompt_version=prompt_version,
                session_id=f"sess-{i % 10}",
                status=status,
                start_time=start,
                end_time=start + timedelta(milliseconds=latency),
                latency_ms=latency,
                total_tokens=prompt_tokens + completion_tokens,
                total_cost_usd=cost,
            )
        )
        objects.append(
            Span(
                trace_id=tid,
                name="retrieve",
                kind=SpanKind.RETRIEVAL.value,
                input="user question",
                output="[retrieved chunks]",
                start_time=start,
            )
        )
        objects.append(
            Span(
                trace_id=tid,
                name="generate",
                kind=SpanKind.LLM.value,
                model=model,
                input="prompt",
                output="generated answer ...",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                status=status,
                error="simulated failure" if errored else None,
                start_time=start,
            )
        )
        objects.append(_score(tid, "no_error", not errored, status, start))
        objects.append(
            _score(
                tid,
                "latency_budget",
                latency <= LATENCY_BUDGET_MS,
                f"{latency}ms vs {LATENCY_BUDGET_MS}ms",
                start,
            )
        )
        objects.append(
            _score(
                tid,
                "cost_budget",
                cost <= COST_BUDGET_USD,
                f"${cost:.4f} vs ${COST_BUDGET_USD}",
                start,
            )
        )

    with session_factory() as session:
        session.add_all(objects)
        session.commit()
    return n


def main() -> None:
    from llm_observatory.db import get_engine, init_db, session_factory

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)
    count = seed_demo(factory)
    logger.info("Seeded %d demo traces (with a regression in the recent window)", count)


if __name__ == "__main__":
    main()
