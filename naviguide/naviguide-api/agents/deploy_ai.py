"""
NAVIGUIDE Simulation Agents — Anthropic Claude LLM Client
Shared client for LLM calls via the Anthropic API (claude-opus-4-5 by default).
Degrades gracefully when ANTHROPIC_API_KEY is not configured.
"""

import os
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()

# Model to use — overridable via env var
_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")

# Lazy-initialised Anthropic client (avoids import error if SDK not installed)
_client = None


def _get_client():
    """Return a cached Anthropic client, or None if SDK / key is unavailable."""
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        _client = Anthropic(api_key=api_key)
        return _client
    except Exception:
        return None


def call_llm(prompt: str, system: str = "") -> Tuple[str, str]:
    """
    Send a prompt to the Anthropic Claude API.

    Args:
        prompt  — user message content
        system  — optional system prompt (defaults to empty)

    Returns:
        (content, data_freshness) where data_freshness is one of:
            'training_only' — response generated from LLM training data
    Falls back to ("", "training_only") when the service is unavailable.
    """
    client = _get_client()
    if client is None:
        return "", "training_only"

    try:
        kwargs = {
            "model":      _MODEL,
            "max_tokens": 1024,
            "messages":   [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        message = client.messages.create(**kwargs)
        content = message.content[0].text
        return content, "training_only"
    except Exception:
        return "", "training_only"
