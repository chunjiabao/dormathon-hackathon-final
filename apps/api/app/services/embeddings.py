"""Local sentence embeddings (sentence-transformers/all-MiniLM-L6-v2, 384-d) via ONNX (fastembed).

Runs fully locally after a one-time model download; no LLM or external API is called. If the
model cannot be loaded, semantic matching is reported as unavailable and the cache falls back
to exact/alias matching only (never silently claiming semantic caching works).
"""

import logging
import threading
from functools import lru_cache

import numpy as np

from app.config import get_settings

log = logging.getLogger("tokenguard")
_lock = threading.Lock()
_state: dict = {"model": None, "error": None}


class EmbeddingUnavailable(RuntimeError):
    pass


def _load():
    settings = get_settings()
    if settings.embedding_mode == "disabled":
        raise EmbeddingUnavailable("embedding_mode=disabled")
    with _lock:
        if _state["model"] is None and _state["error"] is None:
            try:
                from fastembed import TextEmbedding

                _state["model"] = TextEmbedding(settings.embedding_model, cache_dir=settings.embedding_cache_dir)
            except Exception as exc:  # noqa: BLE001 - degrade to exact matching, report status
                _state["error"] = f"{type(exc).__name__}: {exc}"[:200]
                log.warning("Embedding model unavailable; semantic cache disabled: %s", _state["error"])
        if _state["model"] is None:
            raise EmbeddingUnavailable(_state["error"] or "not loaded")
        return _state["model"]


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised embeddings, shape (n, 384)."""
    vecs = np.asarray(list(_load().embed(texts)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-12)


@lru_cache(maxsize=4096)
def embed_one(text: str) -> tuple[float, ...]:
    return tuple(embed([text])[0].tolist())


def status() -> dict:
    """Never triggers a model load (health checks must stay fast)."""
    settings = get_settings()
    if settings.embedding_mode == "disabled":
        return {"semantic_matching": "disabled", "model": None}
    if _state["model"] is not None:
        return {"semantic_matching": "available", "model": settings.embedding_model, "dimensions": 384}
    if _state["error"] is not None:
        return {"semantic_matching": "unavailable", "model": settings.embedding_model, "error": _state["error"]}
    return {"semantic_matching": "loading", "model": settings.embedding_model}


def warm_in_background() -> None:
    if get_settings().embedding_mode == "local":
        threading.Thread(target=lambda: _safe_warm(), daemon=True, name="embedding-warmup").start()


def _safe_warm() -> None:
    try:
        warm()
    except EmbeddingUnavailable:
        pass


def warm() -> None:
    """Download/load the model ahead of time (e.g. during the Docker build)."""
    embed(["warm up"])
