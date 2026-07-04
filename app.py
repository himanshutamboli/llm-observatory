"""llm-observatory dashboard (Streamlit).

Day 29: filterable trace list over the store.py query layer. Trace detail (Day 30)
and trends (Day 31) build on this shell.

Run with:  uv run streamlit run app.py
"""

import streamlit as st
from sqlalchemy import distinct, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import Trace
from llm_observatory.seed import seed_demo
from llm_observatory.store import TraceFilter, count_traces, list_traces

st.set_page_config(page_title="llm-observatory", page_icon="🛰️", layout="wide")


@st.cache_resource
def get_factory():
    engine = get_engine()
    init_db(engine)  # idempotent; alembic-managed in prod
    return session_factory(engine)


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
