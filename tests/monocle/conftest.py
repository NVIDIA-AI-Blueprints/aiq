"""Pytest scaffold for the AI-Q (NeMo Agent Toolkit) Monocle test suite.

Enables Monocle tracing, loads the repo `deploy/.env`, and exposes
``run_nvidiaaiq`` -- the single entry the live tests use to drive the agent
under instrumentation and return its final answer text.
"""
import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from monocle_apptrace import setup_monocle_telemetry

HERE = Path(__file__).resolve().parent
TRACES = HERE / "traces"
REPO_ROOT = HERE.parent.parent

# This repo runs pytest with `--import-mode=importlib`, so a test's directory is
# not auto-added to sys.path and `import conftest` would load a *second* copy of
# this module -- double-instrumenting the tracer. Guard the one-time setup.
if not os.environ.get("_NVIDIAAIQ_MONOCLE_READY"):
    setup_monocle_telemetry(workflow_name="nvidia-aiq")
    load_dotenv(REPO_ROOT / "deploy" / ".env")
    os.environ["_NVIDIAAIQ_MONOCLE_READY"] = "1"

# The CLI-mode workflow used for live runs. It exposes the web/paper search
# tools and a human-in-the-loop clarification + plan-approval step.
LIVE_CONFIG = REPO_ROOT / "configs" / "config_openai_cli.yml"


def run_nvidiaaiq(message: str) -> str:
    """Run the AI-Q (NAT) workflow once and return its final response text.

    NAT's CLI workflow can raise a human-in-the-loop interrupt (clarification or
    plan approval). We pass an auto-approving ``user_input_callback`` so the run
    never blocks waiting on a human -- a short affirmative satisfies both the
    clarifier and plan approval.
    """
    from nat.builder.context import ContextState
    from nat.data_models.interactive import HumanResponseText
    from nat.runtime.loader import load_workflow

    async def _auto_approve(prompt):
        return HumanResponseText(text="Yes, proceed with the research plan.")

    async def _run() -> str:
        async with load_workflow(str(LIVE_CONFIG)) as session_manager:
            try:
                ContextState.get().conversation_id.set(str(uuid.uuid4()))
            except Exception:
                pass
            async with session_manager.session(user_input_callback=_auto_approve) as session:
                async with session.run(message) as runner:
                    return await runner.result(to_type=str)

    return asyncio.run(_run())
