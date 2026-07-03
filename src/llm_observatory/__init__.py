"""llm-observatory: LLM observability & evaluation platform (see docs/design.md)."""

from llm_observatory.logging_config import get_logger

__version__ = "0.1.0"

logger = get_logger(__name__)


def main() -> None:
    logger.info("llm-observatory %s — see docs/design.md for the plan", __version__)
