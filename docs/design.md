# llm-observatory — Design (PRD + Architecture)

> Status: **Draft v0.1** (Day 7 flagship design). This is the north star for the
> build in Days 22–35. It will change as we build; that's expected.

---

## 1. One-liner

An **LLM observability & evaluation platform**: capture every LLM call as a
trace, score it (offline on datasets and online on live traffic), detect quality
regressions across model/prompt versions, and surface it all in a dashboard with
alerting. Think "Datadog + a test suite, for LLM apps."

## 2. Problem & motivation

LLM apps fail silently. A prompt tweak or model upgrade can quietly degrade
answer quality, inflate cost, or add latency — and teams find out from users,
not dashboards. Traditional APM captures latency and errors but not *quality*
("was the answer faithful/correct?"). Teams need one place that answers:

- What did this LLM call actually cost, in tokens/dollars/latency?
- Is quality trending down after the last prompt/model change?
- Which traces are failing, and why?

## 3. Users (personas)

- **AI/LLM engineer** — debugs individual traces, compares prompt versions.
- **ML platform / LLMOps** — watches cost/latency/quality trends, sets alerts.
- **Product / TPM** — reads high-level quality & cost dashboards for release go/no-go.

## 4. Goals / Non-goals

**Goals**
- Low-overhead SDK to instrument any Python LLM app (decorator + context manager).
- Persist traces, spans, and eval scores in a queryable store.
- Offline eval: run an evaluator suite over a *versioned* dataset.
- Online eval: sample live traces and score them asynchronously.
- Regression detection across model/prompt versions.
- Dashboard (traces list, trace detail, trends) + threshold alerting.

**Non-goals (v1)**
- Not a hosted multi-tenant SaaS; single-node, self-hosted.
- Not a full APM (no infra metrics, distributed tracing across services).
- Not high-throughput streaming ingestion; batch/async is fine at portfolio scale.

## 5. Core use cases (user stories)

1. *As an engineer*, I wrap my LLM calls with the SDK and every call shows up as
   a trace with input/output, latency, tokens, and cost.
2. *As an engineer*, I open a trace and see its span tree (retrieval → LLM → tool)
   with per-span i/o, cost, and eval scores.
3. *As LLMOps*, I run an offline eval suite over a gold dataset and get a scored
   report per evaluator.
4. *As LLMOps*, I compare eval-score distributions between `prompt v3` and
   `prompt v4` and get told if v4 regressed.
5. *As LLMOps*, I set "faithfulness pass-rate < 0.85 → alert" and get notified on
   breach.

## 6. Requirements

**Functional**
- SDK captures: input, output, model, prompt/completion tokens, cost, latency,
  status/error, arbitrary metadata; supports nested spans.
- Ingestion API (write) + query API (list/filter traces, fetch trace detail).
- Evaluators: pluggable interface; ship heuristic, reference-based, and
  LLM-as-judge evaluators.
- Offline runner over versioned datasets; persist an eval run + per-item scores.
- Online sampler: sample N% of traces, score asynchronously.
- Regression check: compare score distributions across versions (mean, p50/p95,
  pass-rate) and flag drops beyond a threshold.
- Alerting: threshold breach → webhook/Slack/email stub.

**Non-functional**
- SDK overhead target: < 5 ms per call on the hot path (scoring is async/offline).
- Storage: SQLite for dev, Postgres-ready via an ORM (no raw SQLite-only SQL).
- Everything reproducible; seed/demo script; green CI (lint + tests).

## 7. Architecture overview

```
        Instrumented LLM app
        (@observe / with span(...))
                 │  spans + trace
                 ▼
        ┌─────────────────────┐        ┌───────────────────────────┐
        │  Ingestion API      │ write  │  Storage (SQLite→Postgres) │
        │  (FastAPI+pydantic) ├───────► │  traces · spans · scores  │
        └─────────────────────┘        └───────────┬───────────────┘
                 ▲ query                            │ read
                 │                                  ▼
   ┌─────────────┴───────┐   ┌───────────────────────────────────────┐
   │ Online eval sampler │   │   Offline eval runner (versioned      │
   │ (sample live traces)│   │   dataset → evaluators → scores)      │
   └──────────┬──────────┘   └──────────────────┬────────────────────┘
              │  scores                          │  scores
              └──────────────┬───────────────────┘
                             ▼
        ┌────────────┬───────────────┬─────────────┐
        ▼            ▼               ▼             ▼
   Regression    Dashboard       Alerting     (self-eval:
   detection     (Streamlit)   (webhook/Slack)  Day 40 the
                                                 agent repo is
                                                 traced HERE)
```

## 8. Data model (initial)

Concrete tables; types are indicative (ORM: SQLModel/SQLAlchemy).

**trace**
| field | type | notes |
|---|---|---|
| id | uuid (pk) | |
| name | str | logical operation, e.g. "rag_answer" |
| session_id | str? | groups related traces |
| model | str? | primary model used |
| prompt_version | str? | for regression grouping |
| status | enum(ok, error) | |
| start_time / end_time | datetime | |
| latency_ms | int | |
| total_tokens | int | sum over spans |
| total_cost_usd | float | sum over spans |
| metadata | json | free-form |

**span**
| field | type | notes |
|---|---|---|
| id | uuid (pk) | |
| trace_id | fk → trace | |
| parent_span_id | fk → span? | nesting |
| name | str | |
| kind | enum(llm, retrieval, tool, function) | |
| input / output | text/json | |
| model | str? | |
| prompt_tokens / completion_tokens | int | |
| cost_usd | float | |
| latency_ms | int | |
| status / error | enum / text | |

**eval_score**
| field | type | notes |
|---|---|---|
| id | uuid (pk) | |
| target_type | enum(trace, span) | |
| target_id | uuid | |
| evaluator | str | e.g. "faithfulness_llm_judge" |
| mode | enum(offline, online) | |
| score | float | normalized 0..1 where possible |
| passed | bool? | vs a threshold |
| rationale | text? | judge explanation |
| dataset_id / run_id | fk? | offline only |
| config_version | str | evaluator/prompt version |
| created_at | datetime | |

**Offline eval:** `dataset(id, name, version)`, `dataset_item(id, dataset_id,
input, expected)`, `eval_run(id, dataset_id, model, prompt_version,
config_version, created_at)`.

**Alerting:** `alert_rule(id, metric, comparator, threshold, window, channel)`,
`alert_event(id, rule_id, value, fired_at)`.

## 9. Eval taxonomy

- **Heuristic / deterministic** — JSON validity, regex, length, latency, cost caps.
- **Reference-based** — exact match, embedding similarity vs `expected`.
- **LLM-as-judge** — faithfulness, relevance, correctness with a rubric; must be
  spot-checked against human labels and calibrated (know its failure modes).
- **Human labels** — small gold set to calibrate the judges.

## 10. Tech choices

- **Python 3.13**, packaged with `uv` (this template's baseline).
- **FastAPI + pydantic** — typed ingest/query API.
- **SQLModel/SQLAlchemy** over **SQLite → Postgres** — no SQLite-only SQL.
- **Streamlit** dashboard (reuses the skill from `product-analytics-mini`; a light
  React front end is the alternative if time allows).
- **httpx + pytest** for API tests; structured logging via the template's logger.

## 11. Milestones (maps to the 45-day plan)

| Day | Deliverable |
|---|---|
| 22 | Data model + migrations (trace/span/eval_score) |
| 23 | Instrumentation SDK (decorator/context-manager, tokens/cost/latency) |
| 24 | Trace write path + query API (list/filter) |
| 25 | Offline eval runner over a versioned dataset |
| 26 | Online eval sampler (async scoring) |
| 27 | Regression detection across versions |
| 28 | Architecture doc refresh + half the README |
| 29–31 | Dashboard: trace list → trace detail → trends |
| 32 | Alerting (threshold → webhook/Slack/email stub) |
| 33 | Demo data seed + realistic scenario |
| 34 | Final diagram + demo video |
| 35 | Ship v1.0 |

## 12. Risks & open questions

- **LLM-judge reliability** — judges are noisy; mitigate with rubrics, calibration
  against human labels, and reporting judge-vs-human agreement.
- **Cost of online eval** — sampling rate must be tunable; scoring off the hot path.
- **Schema churn** — traces/spans schema may evolve; use migrations from Day 22.
- **Real vs mock LLM** — build against a provider-agnostic client; demo can use a
  mock so CI needs no API keys.
- **Open:** Streamlit vs React for the dashboard — decide by Day 29 based on time.

## 13. Success metrics (for the demo)

- SDK captures a full trace/span tree for a mock RAG app with correct token/cost math.
- Offline eval produces a scored report over a gold dataset.
- A **seeded regression** (deliberately worse prompt) is *detected* by the
  regression module — the money demo.
- Threshold breach fires an alert (stub).
- **Cross-link:** on Day 40, the `agentic-workflow` repo is instrumented by this
  platform — every agent run is traced and scored here.
