import json
from datetime import UTC, datetime, timedelta

import pytest

from llm_observatory import alerting
from llm_observatory.alerting import (
    AlertEvaluation,
    AlertRule,
    MemoryNotifier,
    WebhookNotifier,
    avg_latency_ms,
    check_alerts,
    error_rate,
    evaluate_rule,
    evaluator_pass_rate,
)
from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import EvalScore, Trace

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=5)


def _score(tid, ok):
    return EvalScore(
        target_type="trace",
        target_id=tid,
        evaluator="no_error",
        mode="online",
        score=1.0 if ok else 0.0,
        passed=ok,
    )


@pytest.fixture
def factory(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    f = session_factory(engine)
    with f() as s:
        recent = [
            Trace(
                id="r1", name="x", status="ok", start_time=NOW - timedelta(days=1), latency_ms=100
            ),
            Trace(
                id="r2", name="x", status="ok", start_time=NOW - timedelta(days=2), latency_ms=100
            ),
            Trace(
                id="r3", name="x", status="ok", start_time=NOW - timedelta(days=3), latency_ms=100
            ),
            Trace(
                id="r4",
                name="x",
                status="error",
                start_time=NOW - timedelta(days=4),
                latency_ms=5000,
            ),
        ]
        old = Trace(
            id="o1", name="x", status="error", start_time=NOW - timedelta(days=10), latency_ms=9000
        )
        s.add_all(
            [
                *recent,
                old,
                _score("r1", True),
                _score("r2", True),
                _score("r3", True),
                _score("r4", False),
            ]
        )
        s.commit()
    return f


def test_metrics_respect_window(factory):
    with factory() as s:
        assert error_rate(s, SINCE) == 0.25  # 1 of 4 recent (old excluded)
        assert avg_latency_ms(s, SINCE) == 1325.0  # (100+100+100+5000)/4
        assert evaluator_pass_rate(s, "no_error", SINCE) == 0.75


def test_evaluate_rule_breach_and_ok(factory):
    with factory() as s:
        hot = evaluate_rule(s, AlertRule("e", "error_rate", ">", 0.15, 5), now=NOW)
        assert hot.breached and hot.value == 0.25
        cool = evaluate_rule(s, AlertRule("l", "avg_latency_ms", ">", 2000, 5), now=NOW)
        assert not cool.breached and cool.value == 1325.0


def test_check_alerts_fires_only_breaches(factory):
    rules = [
        AlertRule("err", "error_rate", ">", 0.15, 5),
        AlertRule("lat", "avg_latency_ms", ">", 2000, 5),  # 1325 -> ok
        AlertRule("pass", "pass_rate:no_error", "<", 0.85, 5),
    ]
    notifier = MemoryNotifier()
    with factory() as s:
        fired = check_alerts(s, rules, notifier, now=NOW)
    fired_names = {e.rule.name for e in fired}
    assert fired_names == {"err", "pass"}
    assert {e.rule.name for e in notifier.fired} == {"err", "pass"}


def test_unknown_metric_raises(factory):
    with factory() as s, pytest.raises(ValueError):
        evaluate_rule(s, AlertRule("x", "bogus_metric", ">", 1.0), now=NOW)


def test_webhook_notifier_posts_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)

    monkeypatch.setattr(alerting.urllib.request, "urlopen", fake_urlopen)
    evaluation = AlertEvaluation(AlertRule("err", "error_rate", ">", 0.15), 0.25, True)
    WebhookNotifier("https://hooks.example.com/x").notify(evaluation)

    assert captured["url"] == "https://hooks.example.com/x"
    assert captured["body"]["metric"] == "error_rate"
    assert captured["body"]["value"] == 0.25
