# llm-observatory 🛰️

[![CI](https://github.com/himanshutamboli/llm-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/himanshutamboli/llm-observatory/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](https://github.com/astral-sh/ruff)
[![status](https://img.shields.io/badge/status-building-blue.svg)](docs/design.md)

> An **LLM observability & evaluation platform** — capture every LLM call as a
> trace, score it (offline on datasets + online on live traffic), detect quality
> regressions across model/prompt versions, and see it all in a dashboard with
> alerting. *Datadog + a test suite, for LLM apps.*

## Status

🏗️ **Building** (Days 22–35). Full PRD + architecture in **[`docs/design.md`](docs/design.md)**.

- **Day 22 ✅ — data model + migrations.** `traces`, `spans`, `eval_scores` as SQLAlchemy 2.0
  models with a SQLite→Postgres-ready storage layer and Alembic migrations.
- **Day 23 ✅ — instrumentation SDK.** `trace`/`span` context managers + an `@observe`
  decorator that capture input/output, latency, tokens, and cost; pluggable `Writer`
  (memory for tests, DB for persistence).
- **Day 24 ✅ — query layer.** `store.py`: list/filter traces (session, model, prompt
  version, status, time window) with pagination + count, and fetch a single trace with
  its spans — the read side the dashboard sits on.
- **Day 25 ✅ — offline eval runner.** `offline_eval.py`: run a target over a versioned
  dataset inside traces, score with pluggable evaluators, persist `eval_score` rows tagged
  with `dataset_id` / `run_id` / `config_version`.
- **Day 26 ✅ — online eval sampler.** `online_eval.py`: deterministically sample live
  traces (by id-hash), score with label-free trace evaluators (no-error, latency/cost
  budget), dedup, and persist `mode="online"` scores off the hot path (async wrapper).
- **Day 27 ✅ — regression detection.** `regression.py`: compare eval-score distributions
  (n / mean / p50 / p95 / pass-rate) across `config_version`s and flag drops beyond a
  threshold. The demo runs a good v1 and a degraded v2 and **detects** the regression.
- **Day 28 ✅ — architecture writeup.** [`docs/architecture.md`](docs/architecture.md):
  data-flow diagram, component walkthrough, data model, eval taxonomy, design decisions.
- **Day 29 ✅ — dashboard (trace list).** Streamlit `app.py` over the query layer: filter
  traces by model / status / session / prompt version, with counts. `seed.py` populates
  demo data. `uv run streamlit run app.py`.

## Architecture

```
 instrumented app → SDK (trace/span) → Writer → storage (traces·spans·eval_scores)
                                                    │
                    ┌───────────────────────────────┼───────────────────────────┐
                    ▼                                ▼                           ▼
              query layer                offline + online eval           regression
              (list/filter)              (dataset & live traffic)        (version deltas)
                    └──────────────► dashboard + alerting (planned) ◄─────────────┘
```

Full diagram, component table, and design decisions: **[`docs/architecture.md`](docs/architecture.md)**.

## Quickstart

```bash
uv sync --dev
uv run alembic upgrade head                     # create the schema
uv run python -m llm_observatory.sdk            # emit a demo trace
uv run python -m llm_observatory.offline_eval   # score a versioned dataset
uv run python -m llm_observatory.online_eval    # sample + score live traces
uv run python -m llm_observatory.regression     # detect a v1->v2 regression
uv run pytest                                    # full suite (incl. migration tests)
```

## Instrumentation SDK (Day 23)

What an app imports to get observed — capture is decoupled from storage via a `Writer`:

```python
tracer = Tracer(DBWriter(session_factory))
with tracer.trace("rag_answer", model="claude-opus-4-8") as t:
    with t.span("retrieve", kind="retrieval", input=query) as s:
        s.set_output(str(chunks))
    with t.span("generate", kind="llm", model="claude-opus-4-8") as s:
        s.set_output(answer)
        s.set_usage(prompt_tokens=1200, completion_tokens=180)  # cost derived from model price
```

The trace rolls up total tokens/cost from its spans, records latency, and marks
`status="error"` (then re-raises) if the body throws. `uv run python -m llm_observatory.sdk`
runs a demo that persists a trace and prints its rollup (2 spans, 1,380 tokens, $0.0105).

## Data model (Day 22)

A **trace** is one logical operation (e.g. a RAG answer); it holds a tree of **spans**
(llm / retrieval / tool / function) capturing i/o, tokens, cost, latency; **eval scores**
attach to a trace or span, from offline dataset runs or online sampling.

- **Portable types** — string UUIDs, generic `JSON`, no dialect-specific columns — so the
  same models run on SQLite (dev) and Postgres (`LLMOBS_DATABASE_URL`).
- **Alembic migrations** — the initial schema migration is committed and validated in CI
  (`alembic upgrade head` on a fresh DB, and a reversibility check).

```bash
uv sync --dev
uv run alembic upgrade head    # create the schema (SQLite by default)
uv run pytest                  # model CRUD/cascade + migration tests
```

Why design-first for a flagship: writing the data model and component boundaries down
before building prevents the mid-build rewrites that sink ambitious projects.

## Planned architecture (summary)

Instrumentation SDK → Ingestion API → Storage (traces / spans / eval-scores) →
offline + online eval runners → regression detection → dashboard + alerting.
Full diagram and schemas in [`docs/design.md`](docs/design.md).

## Cross-link

On **Day 40**, the `agentic-workflow` flagship gets instrumented *by this
platform* — every agent run traced and scored here. That's the highest-signal
link in the portfolio.

## License

MIT
