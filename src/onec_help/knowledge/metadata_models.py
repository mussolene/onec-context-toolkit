"""Shared datatypes for metadata export → Qdrant (metadata XML export / compact snapshot).

File-system crawling of «выгрузка в файлы» was removed; KD2 XML and JSONL snapshots
still produce :class:`CrawlResult` via :mod:`onec_help.knowledge.kd2_metadata`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ConfigObject:
    """Single configuration object (document, catalog, register, form, etc.)."""

    id: str
    object_type: str
    name: str
    full_name: str | None = None
    path: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConfigRelation:
    """Directed relation between configuration objects."""

    from_id: str
    to_id: str
    relation_type: str


@dataclass(slots=True)
class CrawlResult:
    """In-memory graph for one configuration version (input to :mod:`metadata_graph`)."""

    root_dir: Path
    config_name: str
    config_version: str
    platform_version: str | None = None
    objects: list[ConfigObject] = field(default_factory=list)
    relations: list[ConfigRelation] = field(default_factory=list)

    def iter_objects(self, object_type: str | None = None) -> Iterable[ConfigObject]:
        if object_type is None:
            return iter(self.objects)
        return (o for o in self.objects if o.object_type == object_type)

    def iter_relations(self, relation_type: str | None = None) -> Iterable[ConfigRelation]:
        if relation_type is None:
            return iter(self.relations)
        return (r for r in self.relations if r.relation_type == relation_type)
