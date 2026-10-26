"""Open compressed packs through one source-specific, reusable local cache."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from onec_help.zstd_compat import decompress_path


def cached_extract_path(path: Path, cache_name: str = "query_cache") -> Path:
    # Cache identity includes the source path; equal names and sizes may belong to different workspaces.
    root = Path(
        os.environ.get(
            "ONEC_CONTEXT_CACHE_DIR", str(Path.home() / ".cache" / "onec-context")
        )
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    source_key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20]
    return root / (
        source_key + "." + hashlib.sha256(identity.encode()).hexdigest() + ".db"
    )


def extract_once(path: Path, out_path: Path) -> None:
    # The temporary file shares the destination filesystem, making publication atomic.
    fd, temporary = tempfile.mkstemp(prefix=".onec-", suffix=".db", dir=out_path.parent)
    os.close(fd)
    tmp = Path(temporary)
    try:
        decompress_path(path, tmp)
        os.replace(tmp, out_path)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_sqlite_db(
    path: Path, *, cache_name: str = "query_cache"
) -> tuple[Path, bool]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Knowledge pack does not exist: {path}")
    if path.suffix != ".zst":
        return path, False
    cache = cached_extract_path(path, cache_name)
    if not cache.is_file():
        extract_once(path, cache)
    # Retire only older extractions of this exact source, after the new one exists.
    for old in cache.parent.glob(cache.name.split(".")[0] + ".*.db"):
        if old != cache:
            old.unlink(missing_ok=True)
    return cache, False
