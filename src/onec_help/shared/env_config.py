"""Minimal env config shim for offline local KB building."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def get_unpack_timeout() -> int:
    return _int_env("LOCAL_KB_UNPACK_TIMEOUT", 120)


def get_help_html_max_bytes() -> int:
    return _int_env("LOCAL_KB_HELP_HTML_MAX_BYTES", 10 * 1024 * 1024)


def get_help_file_encoding() -> str:
    return os.getenv("LOCAL_KB_HELP_FILE_ENCODING", "").strip().lower()


def get_data_unpacked_dir() -> str:
    return str((REPO_ROOT / "build" / "kb_work" / "unpacked").resolve())


def get_help_structured_dir() -> str:
    return str((REPO_ROOT / "build" / "kb_work" / "help_structured").resolve())


def get_help_topic_body_max_chars() -> int:
    return _int_env("LOCAL_KB_HELP_TOPIC_BODY_MAX_CHARS", 12000)


def get_qdrant_host() -> str:
    return os.getenv("LOCAL_KB_QDRANT_HOST", "localhost")


def get_qdrant_port() -> int:
    return _int_env("LOCAL_KB_QDRANT_PORT", 6333)


def get_qdrant_timeout() -> int:
    return _int_env("LOCAL_KB_QDRANT_TIMEOUT", 60)


def get_bm25_enabled() -> bool:
    return os.getenv("LOCAL_KB_BM25_ENABLED", "0").strip() in {"1", "true", "yes"}

