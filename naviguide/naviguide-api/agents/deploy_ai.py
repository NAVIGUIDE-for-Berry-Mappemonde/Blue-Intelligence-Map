"""
NAVIGUIDE Simulation Agents — LLM Client (cascade NIM → OpenRouter → Claude)

Shared client for LLM calls, backed by the NAVIGUIDE cascade adapter
(naviguide/llm_cascade.py): NVIDIA NIM first, then OpenRouter, then
Anthropic Claude as a last resort. Providers without an API key are
skipped; degrades gracefully when no key is configured at all.

Provides two calling modes (public API unchanged for the 4 agents):
  - call_llm()   : synchronous, non-streaming (used by LangGraph agent nodes)
  - stream_llm() : async generator, token-by-token streaming (used by FastAPI
                   SSE endpoints to push data: {"token": "..."} events)
"""

import sys
from pathlib import Path
from typing import AsyncIterator, Tuple

from dotenv import load_dotenv

load_dotenv()

# llm_cascade.py lives at the naviguide/ monorepo root, shared with the
# naviguide_workspace services.
_NAVIGUIDE_ROOT = str(Path(__file__).resolve().parents[2])
if _NAVIGUIDE_ROOT not in sys.path:
    sys.path.insert(0, _NAVIGUIDE_ROOT)

from llm_cascade import complete as _cascade_complete  # noqa: E402
from llm_cascade import stream as _cascade_stream  # noqa: E402


def call_llm(prompt: str, system: str = "") -> Tuple[str, str]:
    """
    Send a prompt through the LLM cascade (non-streaming).
    Used internally by LangGraph agent nodes.

    Args:
        prompt  — user message content
        system  — optional system prompt (defaults to empty)

    Returns:
        (content, data_freshness) where data_freshness is 'training_only'.
    Falls back to ("", "training_only") when no provider is available.
    """
    try:
        content, _provider = _cascade_complete(prompt, system=system, max_tokens=1024)
        return content, "training_only"
    except Exception:
        return "", "training_only"


async def stream_llm(prompt: str, system: str = "") -> AsyncIterator[str]:
    """
    Stream tokens through the LLM cascade (NIM → OpenRouter → Claude).
    Async generator — yields individual text tokens as they arrive.

    Used by FastAPI agent endpoints to push SSE data: {"token": "..."} events
    for progressive token-by-token display in the frontend AgentPanel.

    Args:
        prompt  — user message content
        system  — optional system prompt (defaults to empty)

    Yields:
        str — individual text tokens emitted by the first available provider.

    Silently returns (yields nothing) if no provider is available or if an
    unrecoverable error occurs during streaming.
    """
    try:
        async for token in _cascade_stream(prompt, system=system, max_tokens=1024):
            yield token
    except Exception:
        return
