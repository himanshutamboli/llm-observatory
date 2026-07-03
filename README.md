# llm-observatory 🛰️

[![CI](https://github.com/himanshutamboli/llm-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/himanshutamboli/llm-observatory/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](https://github.com/astral-sh/ruff)
[![status](https://img.shields.io/badge/status-in%20design-yellow.svg)](docs/design.md)

> An **LLM observability & evaluation platform** — capture every LLM call as a
> trace, score it (offline on datasets + online on live traffic), detect quality
> regressions across model/prompt versions, and see it all in a dashboard with
> alerting. *Datadog + a test suite, for LLM apps.*

## Status

🚧 **In design.** This repo is initialized and the full PRD + architecture live in
**[`docs/design.md`](docs/design.md)** — data model, components, eval taxonomy,
tech choices, and a day-by-day build plan. Implementation lands in Days 22–35 of
the portfolio plan.

Why design-first: this is a flagship system (traces, evals, regression detection,
dashboard, alerting). Writing the data model and component boundaries down now
prevents the mid-build rewrites that sink ambitious projects.

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
