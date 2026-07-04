"""A realistic end-to-end demo: a mock app instrumented with the SDK, observed by the
platform, plus historical data with a regression — everything the dashboard/video needs.

`observed_answer` is the "app being observed" — a tiny support-bot RAG pipeline wrapped
in the SDK (retrieve span + generate span). `run_demo` populates a full scenario:
backdated history (with a recent regression), a handful of live app calls, online eval
scoring, and an alert check.

Run with:  uv run python -m llm_observatory.demo
"""

from llm_observatory.alerting import DEFAULT_RULES, LoggingNotifier, check_alerts
from llm_observatory.logging_config import get_logger
from llm_observatory.models import SpanKind
from llm_observatory.online_eval import CostBudget, LatencyBudget, NoError, sample_and_score
from llm_observatory.sdk import Tracer
from llm_observatory.seed import seed_demo
from llm_observatory.writer import DBWriter

logger = get_logger(__name__)

# The "knowledge base" the mock support bot answers from.
CORPUS = {
    "reset password": "Go to Settings → Security → Reset Password.",
    "refund policy": "Refunds are available within 30 days of purchase.",
    "cancel subscription": "Cancel anytime under Billing → Manage Plan.",
    "change email": "Update your email under Account → Profile.",
    "export data": "Use Settings → Data → Export to download your data.",
}

DEFAULT_QUERIES = [
    "how do I reset password",
    "what is your refund policy",
    "cancel subscription please",
    "how to change email",
    "teach me to fly a plane",  # out of corpus -> graceful "no info"
]


class MockLLM:
    """Deterministic stand-in for a real LLM (no API key needed)."""

    def complete(self, prompt: str, context: str) -> tuple[str, int, int]:
        answer = context or "I don't have information on that topic."
        prompt_tokens = len(prompt) // 4 + len(context) // 4
        completion_tokens = len(answer) // 4
        return answer, prompt_tokens, completion_tokens


def _retrieve(question: str) -> str:
    q = question.lower()
    for key, doc in CORPUS.items():
        if all(word in q for word in key.split()):
            return doc
    return ""


def observed_answer(tracer: Tracer, question: str, llm: MockLLM | None = None) -> str:
    """The instrumented mock app: one trace, a retrieve span and a generate span."""
    llm = llm or MockLLM()
    with tracer.trace(
        "support_answer", model="claude-opus-4-8", prompt_version="prompt-v2", session_id="live"
    ) as t:
        with t.span("retrieve", kind=SpanKind.RETRIEVAL.value, input=question) as s:
            context = _retrieve(question)
            s.set_output(context or "[no match]")
        with t.span("generate", kind=SpanKind.LLM.value, model="claude-opus-4-8") as s:
            answer, prompt_tokens, completion_tokens = llm.complete(question, context)
            s.set_output(answer)
            s.set_usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return answer


def run_demo(session_factory, seed_n: int = 120, queries: list[str] | None = None) -> dict:
    """Populate a full realistic scenario and return a summary."""
    queries = queries if queries is not None else DEFAULT_QUERIES

    seed_demo(session_factory, n=seed_n)  # backdated history with a recent regression

    tracer = Tracer(DBWriter(session_factory))
    for q in queries:
        observed_answer(tracer, q)  # live app calls, traced now

    online = sample_and_score(
        session_factory, [NoError(), LatencyBudget(2000), CostBudget(0.05)], sample_rate=1.0
    )
    with session_factory() as session:
        fired = check_alerts(session, DEFAULT_RULES, LoggingNotifier())

    return {
        "historical_traces": seed_n,
        "live_traces": len(queries),
        "scores_written": online.n_scored,
        "alerts_fired": [e.rule.name for e in fired],
    }


def main() -> None:
    from llm_observatory.db import get_engine, init_db, session_factory

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)

    summary = run_demo(factory)
    logger.info(
        "Demo ready: %d historical + %d live traces, %d online scores, alerts fired: %s",
        summary["historical_traces"],
        summary["live_traces"],
        summary["scores_written"],
        summary["alerts_fired"],
    )
    logger.info("Open the dashboard:  uv run streamlit run app.py")


if __name__ == "__main__":
    main()
