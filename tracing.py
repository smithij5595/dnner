"""Instrumentation hooks (NO-OP placeholders).

Where instrumentation goes:
  1. setup_tracing()  - called once at startup by app.py and scripts/run_scenarios.py.
                        Register a tracer provider + the LangChain/LangGraph instrumentor here.
  2. trace_context()  - wraps every graph invocation (app.py `respond`, scripts/run_scenarios.py `run_scenario`).
                        Wrap session / user / metadata context managers here.

Nothing else in the codebase references tracing. Agents already use stable run names
("<agent>.<step>") and tags ("agent:<name>", "prompt:<version>") that will show up on spans.
"""
import os
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv

from openai import OpenAI
from arize.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.instrumentation.langchain import LangChainInstrumentor


def setup_tracing():
    """Called once at startup by app.py and scripts/run_scenarios.py.
    Reads ARIZE_SPACE_ID, ARIZE_API_KEY, PROJECT_NAME and OPENAI_API_KEY from .env / the environment."""
    
    load_dotenv()  # Load environment variables from a .env file if present

    ARIZE_SPACE_ID = os.getenv("ARIZE_SPACE_ID")
    ARIZE_API_KEY = os.getenv("ARIZE_API_KEY")
    PROJECT_NAME = os.getenv("PROJECT_NAME")
    #OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    tracer_provider = register(
        space_id=ARIZE_SPACE_ID,
        api_key=ARIZE_API_KEY,
        project_name=PROJECT_NAME,
        batch=False,
    )
    #OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    


@contextmanager
def trace_context(session_id: str, user_id: Optional[str], metadata: dict):
    """Placeholder. Wraps every graph invocation. Later this will wrap
    session/user/metadata context managers. Metadata includes prompt_version,
    injected_failures (list), scenario_id, and detected_intent.

    Note: detected_intent is only known after the graph runs, so callers set
    metadata["detected_intent"] before the block exits (read it on exit if you
    want it as a span attribute)."""
    yield
