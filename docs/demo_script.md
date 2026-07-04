# Demo video script (60–90s)

Setup (before recording):

```bash
uv run python -m llm_observatory.demo        # populate the scenario (history + regression)
uv run streamlit run app.py                  # open http://localhost:8000
```

| Time | Screen | Say |
|---|---|---|
| 0:00–0:08 | Trace list | "This is llm-observatory — Datadog plus a test suite for LLM apps. Every LLM call is captured as a trace." |
| 0:08–0:20 | Filters (pick a model / status=error) | "Filter by model, prompt version, status. Here are the failed calls." |
| 0:20–0:35 | Open a trace (detail) | "Drill into any trace: the span tree — retrieval then generation — with tokens, cost, latency, and its eval scores." |
| 0:35–0:55 | Trends section | "Trends over time. Notice cost and latency climbing, and pass-rate dropping — that's a real regression: prompt-v2 degraded quality." |
| 0:55–1:10 | Terminal: `python -m llm_observatory.regression` | "Regression detection confirms it: exact-match dropped from a good version to the degraded one." |
| 1:10–1:25 | Terminal: `python -m llm_observatory.alerting` | "And alerting fires on the breach — error rate and pass-rate thresholds crossed. This would page a webhook or Slack." |
| 1:25–1:30 | README / repo | "Traces, offline + online evals, regression detection, dashboard, alerting — all tested. On Day 40 it instruments my agent repo too." |

Keep it moving; the story is: **capture → measure → catch the regression → alert.**
