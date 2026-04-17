"""Embedding shim for offline builder-only usage."""

from __future__ import annotations


def get_embedding_dimension() -> int:
    raise RuntimeError("Dense embeddings are not available in the local offline KB builder")


def get_embedding_batch(*_args, **_kwargs):
    raise RuntimeError("Dense embeddings are not available in the local offline KB builder")
