"""llm-observatory dashboard (Streamlit).

Day 29: filterable trace list. Day 30: single-trace detail (spans, i/o, cost, scores).
Trends land on Day 31.

Run with:  uv run streamlit run app.py
"""

import streamlit as st
from sqlalchemy import distinct, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import Trace
from llm_observatory.seed import seed_demo
from llm_observatory.store import TraceFilter, count_traces, get_scores, get_trace, list_traces

st.set_page_config(page_title="llm-observatory", page_icon="🛰️", layout="wide")


@st.cache_resource
def get_factory():
    engine = get_engine()
    init_db(engine)  # idempotent; alembic-managed in prod
    return session_factory(engine)


def render_detail(factory, trace_id: str) -> None:
    with factory() as s:
        trace = get_trace(s, trace_id)
        if trace is None:
            st.warning("Trace not found.")
            return
        scores = get_scores(s, trace_id)

        st.subheader(f"Trace · {trace.name}")
        c = st.columns(4)
        c[0].metric("Status", trace.status)
        c[1].metric("Tokens", trace.total_tokens)
        c[2].metric("Cost ($)", f"{trace.total_cost_usd:.4f}")
        c[3].metric("Latency (ms)", trace.latency_ms or 0)
        st.caption(
            f"model={trace.model} · prompt={trace.prompt_version} · "
            f"session={trace.session_id} · id={trace.id}"
        )

        st.markdown("**Spans**")
        for sp in trace.spans:
            title = f"{sp.kind} · {sp.name} — {sp.latency_ms or 0}ms · ${sp.cost_usd:.4f}"
            with st.expander(title):
                st.write(
                    {
                        "model": sp.model,
                        "prompt_tokens": sp.prompt_tokens,
                        "completion_tokens": sp.completion_tokens,
                        "status": sp.status,
                    }
                )
                if sp.input:
                    st.text_area("input", sp.input, height=68, key=f"in-{sp.id}", disabled=True)
                if sp.output:
                    st.text_area("output", sp.output, height=68, key=f"out-{sp.id}", disabled=True)
                if sp.error:
                    st.error(sp.error)

        st.markdown("**Eval scores**")
        if scores:
            st.dataframe(
                [
                    {
                        "evaluator": sc.evaluator,
                        "mode": sc.mode,
                        "score": sc.score,
                        "passed": sc.passed,
                        "rationale": sc.rationale,
                    }
                    for sc in scores
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No eval scores attached to this trace yet.")


factory = get_factory()

with factory() as s:
    total_all = count_traces(s)
    models = sorted(m for m in s.scalars(select(distinct(Trace.model))) if m)

st.sidebar.title("🛰️ llm-observatory")
if total_all == 0:
    st.sidebar.warning("No traces yet.")
    if st.sidebar.button("Seed demo data"):
        seed_demo(factory)
        st.rerun()

st.sidebar.header("Filters")
model = st.sidebar.selectbox("Model", ["All", *models])
status = st.sidebar.selectbox("Status", ["All", "ok", "error"])
session_id = st.sidebar.text_input("Session id")
prompt_version = st.sidebar.text_input("Prompt version")
limit = st.sidebar.slider("Max rows", 10, 200, 50)

trace_filter = TraceFilter(
    model=None if model == "All" else model,
    status=None if status == "All" else status,
    session_id=session_id or None,
    prompt_version=prompt_version or None,
)

with factory() as s:
    matching = count_traces(s, trace_filter)
    traces = list_traces(s, trace_filter, limit=limit)
    rows = [
        {
            "start": str(t.start_time)[:19],
            "name": t.name,
            "model": t.model,
            "prompt_version": t.prompt_version,
            "status": t.status,
            "tokens": t.total_tokens,
            "cost_usd": round(t.total_cost_usd, 4),
            "latency_ms": t.latency_ms,
            "id": t.id,
        }
        for t in traces
    ]

st.title("Traces")
c1, c2, c3 = st.columns(3)
c1.metric("Matching traces", matching)
c2.metric("Total traces", total_all)
c3.metric("Models seen", len(models))

if rows:
    st.dataframe(rows, width="stretch", hide_index=True)
else:
    st.info("No traces match the current filters.")

# --- Trace detail (deep-linkable via ?trace=...) ---
ids = [r["id"] for r in rows]
selected = st.query_params.get("trace")
options = ["—", *ids]
index = options.index(selected) if selected in options else 0
choice = st.selectbox(
    "Open a trace", options, index=index, format_func=lambda x: x if x == "—" else x[:8]
)
if choice != "—":
    st.query_params["trace"] = choice
    st.divider()
    render_detail(factory, choice)
