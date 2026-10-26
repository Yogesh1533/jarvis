"""Local text embeddings for semantic recall.

A small ONNX model (fastembed) runs on the CPU; nothing here touches the
network except the one-time model download into EMBED_CACHE_DIR. The model
loads lazily so text mode and the tests start without it.
"""
import importlib.util
import threading

import numpy as np

from . import config

DIM = 384   # BAAI/bge-small-en-v1.5

_lock = threading.Lock()
_model = None


class EmbeddingsUnavailable(RuntimeError):
    """fastembed isn't installed, so recall falls back to keyword search."""


def _library_present():
    return importlib.util.find_spec("fastembed") is not None


def set_embedder(model):
    """Inject an object with fastembed's `.embed(texts)` (tests), or None to reset."""
    global _model
    with _lock:
        _model = model


def available():
    return _model is not None or _library_present()


def _load():
    if not _library_present():
        raise EmbeddingsUnavailable(
            "Semantic recall needs the 'fastembed' package: pip install fastembed"
        )
    from fastembed import TextEmbedding

    config.EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.EMBED_CACHE_DIR))


def embed(texts):
    """Embed texts to an (n, 384) float32 array with unit-length rows."""
    global _model
    texts = list(texts)
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    with _lock:   # ONNX sessions aren't promised thread-safe; calls are short
        if _model is None:
            _model = _load()
        rows = [np.asarray(v, dtype=np.float32) for v in _model.embed(texts)]
    matrix = np.stack(rows)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)
