"""
rag_core.py — RAG sémantique local & Smart Chunking (mutualisé PoE / Projets).

- Découpage des PDF/rapports longs en blocs de ~500 caractères.
- Sélection des blocs pertinents par similarité cosinus avant l'appel LLM.
- Monitoring sémantique des sources (skip ré-extraction si contenu quasi identique).
- Re-ranking de candidats (géocodage) par similarité sémantique.

Backend : sentence-transformers (all-MiniLM-L6-v2) si disponible,
sinon repli TF-IDF (scikit-learn) — même API, zéro dépendance dure.
"""
import re

_st_model = None
_st_failed = False
_ce_model = None
_ce_failed = False


def _get_st():
    global _st_model, _st_failed
    if _st_model is not None or _st_failed:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer
        _st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        _st_failed = True
    return _st_model


def _get_ce():
    """Cross-Encoder ms-marco pour le re-ranking (spec) — chargé paresseusement."""
    global _ce_model, _ce_failed
    if _ce_model is not None or _ce_failed:
        return _ce_model
    try:
        from sentence_transformers import CrossEncoder
        _ce_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        _ce_failed = True
    return _ce_model


def embedding_backend() -> str:
    return "sentence-transformers" if _get_st() is not None else "tfidf"


def chunk_text(text: str, size: int = 500, overlap: int = 60) -> list[str]:
    """Smart chunking : blocs ~size chars alignés sur les fins de phrases."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + size // 2, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end].strip())
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _cosine_scores(query: str, docs: list[str]) -> list[float]:
    model = _get_st()
    if model is not None:
        import numpy as np
        emb = model.encode([query] + docs, normalize_embeddings=True)
        return (emb[1:] @ emb[0]).tolist()
    # Repli TF-IDF
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    vec = TfidfVectorizer(ngram_range=(1, 2), max_features=20000).fit([query] + docs)
    m = vec.transform([query] + docs)
    return cosine_similarity(m[0:1], m[1:]).flatten().tolist()


def top_chunks(query: str, text: str, k: int = 8, size: int = 500) -> list[str]:
    chunks = chunk_text(text, size=size)
    if len(chunks) <= k:
        return chunks
    try:
        scores = _cosine_scores(query, chunks)
    except Exception:
        return chunks[:k]
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:k]
    return [chunks[i] for i in sorted(ranked)]  # ordre d'origine préservé


def select_context(query: str, text: str, max_chars: int = 8000, size: int = 500) -> str:
    """Contexte condensé pour le LLM : uniquement les chunks pertinents."""
    if len(text or "") <= max_chars:
        return text or ""
    k = max(2, max_chars // size)
    return "\n…\n".join(top_chunks(query, text, k=k, size=size))[:max_chars]


def rerank_candidates(query: str, candidates: list[str]) -> list[tuple[int, float]]:
    """Retourne [(index, score)] triés par pertinence décroissante.
    Cross-Encoder ms-marco si disponible, sinon bi-encoder/TF-IDF cosinus."""
    if not candidates:
        return []
    if len(candidates) == 1:
        return [(0, 1.0)]
    ce = _get_ce()
    if ce is not None:
        try:
            scores = ce.predict([(query, c) for c in candidates])
            return sorted(((i, float(s)) for i, s in enumerate(scores)), key=lambda x: x[1], reverse=True)
        except Exception:
            pass
    try:
        scores = _cosine_scores(query, candidates)
    except Exception:
        return [(i, 0.0) for i in range(len(candidates))]
    return sorted(((i, float(s)) for i, s in enumerate(scores)), key=lambda x: x[1], reverse=True)


def semantic_similarity(a: str, b: str) -> float:
    """Similarité cosinus document-à-document (monitoring des sources)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    try:
        return max(0.0, min(1.0, _cosine_scores(a[:5000], [b[:5000]])[0]))
    except Exception:
        import difflib
        return difflib.SequenceMatcher(None, a[:3000], b[:3000]).ratio()


def content_changed(old_text: str, new_text: str, threshold: float = 0.95) -> bool:
    """Monitoring sémantique : True seulement si le contenu a réellement changé
    (évite une ré-extraction LLM pour un changement HTML mineur)."""
    if not old_text or not new_text:
        return True
    return semantic_similarity(old_text, new_text) < threshold
