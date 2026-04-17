"""Minimal indexer shim used by the vendored structured-help snapshot builder."""

from __future__ import annotations


def _version_sort_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in str(version or "").split("."):
        try:
            parts.append(int(token))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def get_collection_vector_size(*_args, **_kwargs):
    return None

