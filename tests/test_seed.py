from sqlalchemy import func, select

from llm_observatory.db import get_engine, init_db, session_factory
from llm_observatory.models import Span, Trace
from llm_observatory.seed import seed_demo


def test_seed_demo_creates_traces_with_spans(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    init_db(engine)
    factory = session_factory(engine)

    seed_demo(factory, n=10, seed=1)

    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Trace)) == 10
        # each trace has 2 spans (retrieve + generate)
        assert s.scalar(select(func.count()).select_from(Span)) == 20
        # deterministic seed -> a mix of models present
        models = {m for m in s.scalars(select(Trace.model))}
        assert len(models) >= 2
