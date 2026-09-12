"""Complète vs incrémental — un run Full refait la carte, il ne saute pas le déjà-posé.

``from_scratch=None`` + scope/mode ``full`` → True.
Un Test reste incrémental. Un booléen explicite gagne toujours.
"""
from __future__ import annotations


def resolve_from_scratch(
    explicit: bool | None,
    *,
    scope: str | None = None,
    mode: str | None = None,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    kind = (scope or mode or "full").strip().lower()
    return kind == "full"
