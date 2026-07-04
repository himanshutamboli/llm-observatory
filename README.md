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
