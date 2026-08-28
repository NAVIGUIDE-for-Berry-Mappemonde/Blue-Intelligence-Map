"""
server.py — Shim de compatibilité : l'application vit dans app/main.py.
Permet de conserver la commande historique `uvicorn server:app`.
"""
from app.main import app  # noqa: F401
