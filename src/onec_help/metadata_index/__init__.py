"""Source-driven metadata indexing helpers for 1C configuration exports."""

from .configdump import (
    build_snapshot_from_config_source,
    detect_config_source_kind,
    find_config_roots,
    get_config_source_info,
    is_config_source_root,
    list_config_source_infos,
    source_identity_stem,
)

__all__ = [
    "build_snapshot_from_config_source",
    "detect_config_source_kind",
    "find_config_roots",
    "get_config_source_info",
    "is_config_source_root",
    "list_config_source_infos",
    "source_identity_stem",
]
