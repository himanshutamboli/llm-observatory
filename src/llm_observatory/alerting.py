"""Alerting: evaluate threshold rules over recent data and notify on breach.

A rule is `metric <comparator> threshold` over a trailing `window_days`. Metrics are
computed from stored traces/scores:

* ``error_rate``          — fraction of traces with status "error"
* ``avg_latency_ms``      — mean trace latency
* ``pass_rate:<evaluator>`` — pass rate for that evaluator's scores

On breach a `Notifier` fires — `LoggingNotifier` (default), `WebhookNotifier` (POSTs JSON,
works with a Slack incoming webhook), or `MemoryNotifier` (tests). Stateless by design.

Run a demo with:  uv run python -m llm_observatory.alerting
"""

import json
import operator
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from llm_observatory.logging_config import get_logger
from llm_observatory.models import EvalScore, Trace
from llm_observatory.store import TraceFilter, list_traces

logger = get_logger(__name__)

COMPARATORS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass
class AlertRule:
    name: str
    metric: str  # "error_rate" | "avg_latency_ms" | "pass_rate:<evaluator>"
    comparator: str  # one of COMPARATORS
    threshold: float
    window_days: int = 7


@dataclass
class AlertEvaluation:
    rule: AlertRule
    value: float
    breached: bool


def error_rate(session: Session, since: datetime) -> float:
    traces = list_traces(session, TraceFilter(since=since), limit=1_000_000)
    if not traces:
        return 0.0
    return sum(1 for t in traces if t.status == "error") / len(traces)


def avg_latency_ms(session: Session, since: datetime) -> float:
    traces = list_traces(session, TraceFilter(since=since), limit=1_000_000)
    if not traces:
        return 0.0
    return sum((t.latency_ms or 0) for t in traces) / len(traces)


def evaluator_pass_rate(session: Session, evaluator: str, since: datetime) -> float:
    stmt = (
        select(EvalScore.passed)
        .join(Trace, EvalScore.target_id == Trace.id)
        .where(EvalScore.evaluator == evaluator, Trace.start_time >= since)
    )
    passes = list(session.scalars(stmt))
    if not passes:
        return 1.0  # no data -> treat as healthy (don't false-fire "< threshold" rules)
    return sum(1 for p in passes if p) / len(passes)


def _metric_value(session: Session, metric: str, since: datetime) -> float:
    if metric == "error_rate":
        return error_rate(session, since)
    if metric == "avg_latency_ms":
        return avg_latency_ms(session, since)
    if metric.startswith("pass_rate:"):
        return evaluator_pass_rate(session, metric.split(":", 1)[1], since)
    raise ValueError(f"unknown metric: {metric}")


class Notifier(Protocol):
    def notify(self, evaluation: AlertEvaluation) -> None: ...


class LoggingNotifier:
    def notify(self, evaluation: AlertEvaluation) -> None:
        r = evaluation.rule
        logger.warning(
            "ALERT %s: %s = %.3f %s %.3f (window %dd)",
            r.name,
            r.metric,
            evaluation.value,
            r.comparator,
            r.threshold,
            r.window_days,
        )


class MemoryNotifier:
    def __init__(self) -> None:
        self.fired: list[AlertEvaluation] = []

    def notify(self, evaluation: AlertEvaluation) -> None:
        self.fired.append(evaluation)


class WebhookNotifier:
    """POST a JSON payload to a URL (e.g. a Slack incoming webhook)."""

    def __init__(self, url: str) -> None:
        self.url = url

    def notify(self, evaluation: AlertEvaluation) -> None:
        payload = {
            "text": f"🚨 {evaluation.rule.name}",
            "metric": evaluation.rule.metric,
            "value": evaluation.value,
            "threshold": evaluation.rule.threshold,
            "comparator": evaluation.rule.comparator,
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=5)  # noqa: S310 (trusted operator URL)
        except OSError as exc:
            logger.error("Webhook notify failed: %s", exc)


def evaluate_rule(
    session: Session, rule: AlertRule, now: datetime | None = None
) -> AlertEvaluation:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=rule.window_days)
    value = _metric_value(session, rule.metric, since)
    breached = COMPARATORS[rule.comparator](value, rule.threshold)
    return AlertEvaluation(rule, value, breached)


def check_alerts(
    session: Session,
    rules: list[AlertRule],
    notifier: Notifier | None = None,
    now: datetime | None = None,
) -> list[AlertEvaluation]:
    """Evaluate all rules; notify on each breach. Returns the breached evaluations."""
    notifier = notifier or LoggingNotifier()
    fired = []
    for rule in rules:
        evaluation = evaluate_rule(session, rule, now=now)
        if evaluation.breached:
            notifier.notify(evaluation)
            fired.append(evaluation)
    return fired


DEFAULT_RULES = [
    AlertRule("High error rate", "error_rate", ">", 0.15, window_days=5),
    AlertRule("Low no-error pass rate", "pass_rate:no_error", "<", 0.85, window_days=5),
    AlertRule("Latency budget breached", "avg_latency_ms", ">", 2000, window_days=5),
]


def main() -> None:
    from llm_observatory.db import get_engine, init_db, session_factory

    engine = get_engine()
    init_db(engine)
    factory = session_factory(engine)
    with factory() as session:
        fired = check_alerts(session, DEFAULT_RULES)
    logger.info("%d/%d rules breached", len(fired), len(DEFAULT_RULES))


if __name__ == "__main__":
    main()
