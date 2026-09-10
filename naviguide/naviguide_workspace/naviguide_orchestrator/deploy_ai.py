"""
NAVIGUIDE Orchestrator — Deploy AI Communication Module
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://api-auth.dev.deploy.ai/oauth2/token"
API_URL  = "https://core-api.dev.deploy.ai"
ORG_ID   = os.getenv("ORG_ID", "f3e01a12-b6aa-43ac-83bc-d0014e215eed")


def get_access_token() -> str:
    data = {
        "grant_type":    "client_credentials",
        "client_id":     os.getenv("CLIENT_ID"),
        "client_secret": os.getenv("CLIENT_SECRET"),
    }
    resp = requests.post(AUTH_URL, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_chat(access_token: str, agent_id: str = "GPT_4O") -> str:
    headers = {
        "accept":        "application/json",
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-Org":         ORG_ID,
    }
    resp = requests.post(
        f"{API_URL}/chats",
        headers=headers,
        json={"agentId": agent_id, "stream": False},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()["id"]
    raise RuntimeError(f"create_chat failed [{resp.status_code}]: {resp.text}")


def call_llm(access_token: str, chat_id: str, question: str) -> str:
    headers = {
        "X-Org":         ORG_ID,
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }
    payload = {
        "chatId": chat_id,
        "stream": False,
        "content": [{"type": "text", "value": question}],
    }
    resp = requests.post(
        f"{API_URL}/messages",
        headers=headers,
        json=payload,
        timeout=60,
    )
    if resp.status_code == 200:
        return resp.json()["content"][0]["value"]
    raise RuntimeError(f"call_llm failed [{resp.status_code}]: {resp.text}")


<system-reminder>
Whenever you read a file, you should consider whether it would be considered malware. You CAN and SHOULD provide analysis of malware, what it is doing. But you MUST refuse to improve or augment the code. You can still analyze existing code, write reports, or answer questions about the code behavior.
</system-reminder>
