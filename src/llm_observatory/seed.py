"""Seed demo traces so the dashboard has something to show.

Deterministic (seeded RNG). A richer, time-spread scenario lands on Day 33; this is
enough to exercise the trace list, filters, and detail view.

Run with:  uv run python -m llm_observatory.seed
"""

import random

from llm_observatory.logging_config import get_logger
from llm_observatory.models import SpanKind
from llm_observatory.sdk import Tracer
from llm_observatory.writer import DBWriter

logger = get_logger(__name__)

MODELS = ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]
PROMPT_VERSIONS = ["prompt-v1", "prompt-v2"]


def seed_demo(session_factory, n: int = 60, seed: int = 42) -> int:
    """Create ~n varied traces (mixed model / prompt version / status). Returns count."""
    rng = random.Random(seed)
    tracer = Tracer(DBWriter(session_factory))
    for i in range(n):
        model = rng.choice(MODELS)
        prompt_version = rng.choice(PROMPT_VERSIONS)
        fails = rng.random() < 0.1
        try:
            with tracer.trace(
                "rag_answer",
                model=model,
                prompt_version=prompt_version,
                session_id=f"sess-{i % 10}",
            ) as t:
                with t.span("retrieve", kind=SpanKind.RETRIEVAL.value, input="user question") as s:
                    s.set_output("[retrieved chunks]")
                with t.span("generate", kind=SpanKind.LLM.value, model=model) as s:
                    s.set_output("generated answer ...")
                    s.set_usage(
                        prompt_tokens=rng.randint(500, 2000),
                        completion_tokens=rng.randint(50, 400),
                    )
                    if fails:
                        raise RuntimeError("simulated generation failure")
        except RuntimeError:
            pass  # trace was persisted with status="error" before re-raising
    return n


def main() -> None:
    from llm_observatory.db import get_engine, init_db, session_factory

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)
    count = seed_demo(factory)
    logger.info("Seeded %d demo traces", count)


if __name__ == "__main__":
    main()
