"""Small zstd compatibility layer for Python 3.11+ runtimes.

Prefer stdlib ``compression.zstd`` when available, then fall back to the
third-party ``zstandard`` package, and finally to the ``zstd`` CLI.
"""

from __future__ import annotations

import subprocess

try:  # Python 3.14+
    import compression.zstd as _zstd
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    _zstd = None

try:  # Optional runtime dependency
    import zstandard as _zstandard  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _zstandard = None


def compress(data: bytes, *, level: int = 9) -> bytes:
    if _zstd is not None:
        return _zstd.compress(data, level=level)
    if _zstandard is not None:
        return _zstandard.ZstdCompressor(level=level).compress(data)
    result = subprocess.run(
        ["zstd", f"-{level}", "-q", "--stdout"],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout


def decompress(data: bytes) -> bytes:
    if _zstd is not None:
        return _zstd.decompress(data)
    if _zstandard is not None:
        return _zstandard.ZstdDecompressor().decompress(data)
    result = subprocess.run(
        ["zstd", "-q", "-d", "--stdout"],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout
