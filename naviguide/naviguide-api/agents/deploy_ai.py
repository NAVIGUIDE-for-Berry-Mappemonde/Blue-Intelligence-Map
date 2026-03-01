"""
NAVIGUIDE Simulation Agents — Deploy AI Communication Module
Shared OAuth2 client for LLM calls via Deploy AI core API.
Degrades gracefully when credentials are not configured.
"""

import os
import requests
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = os.getenv("AUTH_URL", "https://api-auth.deploy.ai/oauth2/token")
API_URL  = os.getenv("API_URL",  "https://core-api.deploy.ai")
ORG_ID   = os.getenv("ORG_ID",   "")
AGENT_ID = os.getenv("DEPLOY_AI_AGENT_ID", "gpt_4o")


def get_access_token() -> Optional[str]:
    """Retrieve OAuth2 client_credentials token from Deploy AI."""
    client_id     = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    try:
        resp = requests.post(
            AUTH_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception:
        return None


def create_chat(access_token: str) -> Optional[str]:
    """Create a new Deploy AI chat session and return the chat ID."""
    try:
        resp = requests.post(
            f"{API_URL}/chats",
            headers={
                "accept":        "application/json",
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {access_token}",
                "X-Org":         ORG_ID,
            },
            json={"agentId": AGENT_ID, "stream": False},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        return None


def call_llm(prompt: str) -> Tuple[str, str]:
    """
    Send a prompt to the Deploy AI LLM.

    Returns:
        (content, data_freshness) where data_freshness is one of:
            'live'          — external API data was fetched and merged
            'training_only' — response generated from LLM training data only
    Falls back to ("", "training_only") when the service is unavailable.
    """
    token = get_access_token()
    if not token:
        return "", "training_only"

    chat_id = create_chat(token)
    if not chat_id:
        return "", "training_only"

    try:
        resp = requests.post(
            f"{API_URL}/messages",
            headers={
                "X-Org":         ORG_ID,
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "chatId": chat_id,
                "stream": False,
                "content": [{"type": "text", "value": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["value"]
        return content, "training_only"
    except Exception:
        return "", "training_only"
