# llm-observatory — Architecture

Companion to [`design.md`](design.md) (the PRD). This documents *what was built* and how
the pieces fit, as of Day 27 (core engine complete; dashboard + alerting remain).

## One-liner

Capture every LLM call as a **trace** of **spans**, **evaluate** it (offline on datasets +
online on live traffic), and **detect regressions** across prompt/model versions — with a
dashboard and alerting on top. *Datadog + a test suite, for LLM apps.*

## Data flow

```
   Instrumented app
   │  from llm_observatory.sdk import Tracer
   │  with tracer.trace(...) as t, t.span(...) as s: ...
   ▼
 ┌──────────────┐   TraceRecord/SpanRecord    ┌───────────────────────────────┐
 │  SDK (sdk.py)│ ──────────────────────────► │  Writer (writer.py)           │
 │  trace/span  │   (capture: i/o, latency,   │   MemoryWriter | DBWriter     │
 │  @observe    │    tokens, cost rollup)      └───────────────┬───────────────┘
 └──────────────┘                                              │ ORM insert
                                                               ▼
                                        ┌──────────────────────────────────────┐
                                        │  Storage (models.py, Alembic)         │
                                        │  traces · spans · eval_scores         │
                                        │  SQLite (dev) / Postgres (prod)       │
                                        └───────┬───────────────────────┬───────┘
                                       read     │                       │  write scores
                            ┌───────────────────▼─────┐        ┌────────▼──────────────┐
                            │  Query layer (store.py) │        │  Eval                 │
                            │  list/filter/paginate,  │        │  offline_eval.py      │
                            │  get_trace + spans      │        │   (dataset + versioned│
                            └───────────┬─────────────┘        │    config → scores)   │
                                        │                      │  online_eval.py       │
                                        │                      │   (sample live traces │
                                        │                      │    → scores)          │
                                        │                      └────────┬──────────────┘
                                        │                               │  eval_scores
                                        │                               ▼
                                        │                    ┌────────────────────────┐
                                        │                    │  regression.py          │
                                        │                    │  compare score dists    │
                                        │                    │  across config_versions │
                                        │                    └────────────────────────┘
                                        ▼
                        Dashboard (Days 29–31) + Alerting (Day 32)   ← planned
```

## Components

| Module | Responsibility | Key types |
|---|---|---|
| `models.py` | ORM schema, portable across SQLite/Postgres | `Trace`, `Span`, `EvalScore`, `SpanKind`, `EvalMode` |
| `db.py` | Engine + session factory; `LLMOBS_DATABASE_URL` override | `get_engine`, `session_factory`, `init_db` |
| `migrations/` | Alembic schema migrations (validated in CI) | initial-schema revision |
| `sdk.py` | Instrumentation: capture calls as trace/span; cost from tokens | `Tracer`, `_TraceCtx`, `_SpanCtx`, `@observe`, `estimate_cost` |
| `writer.py` | Persistence seam — capture decoupled from storage | `Writer` (protocol), `MemoryWriter`, `DBWriter` |
| `store.py` | Read side: filter/paginate traces, fetch a trace + spans | `TraceFilter`, `list_traces`, `get_trace` |
| `offline_eval.py` | Run a target over a versioned dataset, score, persist | `Dataset`, `Evaluator`, `run_eval` |
| `online_eval.py` | Sample live traces, score off the hot path, persist | `TraceEvaluator`, `sample_and_score` |
| `regression.py` | Compare score distributions across versions, flag drops | `Distribution`, `compare_versions` |

## Data model

- **trace** — one logical operation. Holds rollup metrics (total tokens/cost, latency) and
  grouping keys (`session_id`, `model`, `prompt_version`, `status`).
- **span** — a node in the trace (llm / retrieval / tool / function), with i/o, per-call
  tokens/cost/latency, and `parent_span_id` for nesting. `ondelete=CASCADE`.
- **eval_score** — attaches to a **trace or span** (polymorphic `target_type`/`target_id`,
  intentionally FK-free), from offline runs (`dataset_id`, `run_id`, `config_version`) or
  online sampling (`mode="online"`).

## Eval taxonomy

- **Heuristic / deterministic** — exact match, contains, non-empty, latency/cost budgets.
  No API, CI-safe; the current evaluators.
- **Reference-based** — compare output to an expected value (offline datasets).
- **LLM-as-judge** — faithfulness/quality via a model; must be calibrated against human
  labels (demonstrated in `rag-knowledge-assistant`).
- **Offline vs online** — offline scores a versioned dataset (comparable across runs);
  online scores a sample of real traffic (label-free trace evaluators).

## Design decisions

1. **Portable column types** (string UUIDs, generic JSON) so the same models run on SQLite
   and Postgres — the dev→prod path is real, not aspirational.
2. **Writer seam** — the SDK captures without knowing where traces land; trivially testable
   (`MemoryWriter`) and swappable (DB now, a queue later).
3. **Migrations validated in CI** — `alembic upgrade head` + a reversibility check run in the
   test suite, so a broken migration fails the pipeline.
4. **Versioned eval configs** — scores carry `config_version`/`run_id`, making runs
   comparable; regression detection is then a `GROUP BY` away.
5. **Deterministic sampling** — online sampling is by trace-id hash, so coverage is
   reproducible and the sampler is idempotent (dedup by trace+evaluator).
6. **Distribution comparison, not just means** — regression flags on mean *or* pass-rate
   drop, catching both "slightly worse everywhere" and "a chunk now fails".
7. **stdlib-only stats** — no scipy; the math is transparent and testable.

## Build status

| Days | Component | State |
|---|---|---|
| 22 | Data model + migrations | ✅ |
| 23 | Instrumentation SDK | ✅ |
| 24 | Query layer | ✅ |
| 25 | Offline eval runner | ✅ |
| 26 | Online eval sampler | ✅ |
| 27 | Regression detection | ✅ |
| 29–31 | Dashboard (traces / detail / trends) | ⏳ |
| 32 | Alerting (threshold → webhook/Slack stub) | ⏳ |
| 33–34 | Demo data + docs/diagram/video | ⏳ |
| 35 | Ship v1.0 | ⏳ |

## Cross-link

On **Day 40**, the `agentic-workflow` flagship is instrumented *by this platform* — every
agent run traced and scored here. That mutual citation is the strongest signal in the
portfolio.
