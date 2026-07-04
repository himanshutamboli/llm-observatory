"""Time-series aggregates for the dashboard trends view.

Bucketing is done in Python (group by date) rather than SQL, to stay portable across
SQLite and Postgres. Cost/latency come from traces; score trends join eval scores to
their target trace's start_time (so a score is plotted at the time the traced call ran,
not when it was scored).
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from llm_observatory.models import EvalScore, Trace
from llm_observatory.store import TraceFilter, _apply, list_traces


def cost_latency_series(session: Session, filter: TraceFilter | None = None) -> list[dict]:
    """Per-day n / total cost / avg latency / avg tokens over matching traces."""
    traces = list_traces(session, filter, limit=1_000_000)
    buckets: dict[str, list[Trace]] = defaultdict(list)
    for t in traces:
        buckets[t.start_time.date().isoformat()].append(t)

    series = []
    for period in sorted(buckets):
        group = buckets[period]
        series.append(
            {
                "period": period,
                "n": len(group),
                "total_cost_usd": round(sum(t.total_cost_usd for t in group), 4),
                "avg_latency_ms": round(sum((t.latency_ms or 0) for t in group) / len(group), 1),
                "avg_tokens": round(sum(t.total_tokens for t in group) / len(group), 1),
            }
        )
    return series


def pass_rate_series(
    session: Session, evaluator: str, filter: TraceFilter | None = None
) -> list[dict]:
    """Per-day mean score / pass rate for one evaluator, keyed by the trace's start_time."""
    stmt = (
        select(Trace.start_time, EvalScore.score, EvalScore.passed)
        .join(Trace, EvalScore.target_id == Trace.id)
        .where(EvalScore.evaluator == evaluator)
    )
    stmt = _apply(stmt, filter or TraceFilter())

    buckets: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for start_time, score, passed in session.execute(stmt):
        buckets[start_time.date().isoformat()].append((score, bool(passed)))

    series = []
    for period in sorted(buckets):
        vals = buckets[period]
        series.append(
            {
                "period": period,
                "n": len(vals),
                "mean_score": round(sum(s for s, _ in vals) / len(vals), 3),
                "pass_rate": round(sum(1 for _, p in vals if p) / len(vals), 3),
            }
        )
    return series
