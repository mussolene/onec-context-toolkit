"""Canonical string ids for configuration metadata (KD2 graph, Qdrant payload ``id``)."""

from __future__ import annotations


def make_metadata_object_id(object_type: str, name: str) -> str:
    """Build canonical id: ``EnglishType.ObjectName`` (single dot between type and technical name).

    1C metadata object names normally do not contain ``.``; dotted BSL paths after the first
    segment are handled in query normalization, not in this id.
    """
    ot = (object_type or "").strip()
    nm = (name or "").strip()
    return f"{ot}.{nm}"
