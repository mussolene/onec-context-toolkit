"""Small zstd compatibility layer for Python 3.11+ runtimes.

Prefer stdlib ``compression.zstd`` when available, then fall back to the
third-party ``zstandard`` package, and finally to the ``zstd`` CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

try:  # Python 3.14+
    import compression.zstd as _zstd
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    _zstd = None

try:  # Optional runtime dependency
    import zstandard as _zstandard  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _zstandard = None


def has_python_backend() -> bool:
    return _zstd is not None or _zstandard is not None


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


def compress_path(src: Path, dst: Path, *, level: int = 19) -> int:
    src = src.expanduser().resolve()
    dst = dst.expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _zstandard is not None:
        compressor = _zstandard.ZstdCompressor(level=level)
        with src.open("rb") as in_fp, dst.open("wb") as out_fp:
            with compressor.stream_writer(out_fp) as writer:
                while True:
                    chunk = in_fp.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)
        return dst.stat().st_size
    data = src.read_bytes()
    dst.write_bytes(compress(data, level=level))
    return dst.stat().st_size


def decompress_path(src: Path, dst: Path) -> int:
    src = src.expanduser().resolve()
    dst = dst.expanduser().resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _zstandard is not None:
        dctx = _zstandard.ZstdDecompressor()
        with src.open("rb") as in_fp, dst.open("wb") as out_fp:
            with dctx.stream_reader(in_fp) as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    out_fp.write(chunk)
        return dst.stat().st_size
    data = src.read_bytes()
    dst.write_bytes(decompress(data))
    return dst.stat().st_size


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
