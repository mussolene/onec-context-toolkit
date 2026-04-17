"""Read 1C HBK binary container and extract entities (PackBlock, FileStorage, Book).

Source: alkoleft/hbk-viewer (MIT), based on 1c-syntax/bsl-context.
Format: doc/hbk-binary-format.md, doc/hbk-format.md.
"""

from __future__ import annotations

import struct
from pathlib import Path

CONTAINER_HEADER_SIZE = 16
BLOCK_HEADER_SIZE = 31
FILE_DESCRIPTION_SIZE = 12
SPLITTER = 0x7FFFFFFF  # Int.MAX_VALUE; last block / no body
NAME_CONTENT_OFFSET = 20
NAME_CONTENT_TAIL = 4


def _read_int32_le(data: bytes, offset: int) -> int:
    """Read INT32 little-endian at offset."""
    if offset + 4 > len(data):
        raise ValueError("Not enough data for int32")
    return struct.unpack_from("<i", data, offset)[0]


def _read_hex8(data: bytes, offset: int) -> int:
    """Read 8 ASCII hex digits as integer."""
    if offset + 8 > len(data):
        raise ValueError("Not enough data for hex8")
    s = data[offset : offset + 8].decode("ascii", errors="replace")
    return int(s, 16)


def read_container_header(data: bytes) -> tuple[int, int, int, int]:
    """Parse container header (16 bytes). Returns (free_block, default_size, unknown, reserved)."""
    if len(data) < CONTAINER_HEADER_SIZE:
        raise ValueError("Data shorter than container header")
    return (
        _read_int32_le(data, 0),
        _read_int32_le(data, 4),
        _read_int32_le(data, 8),
        _read_int32_le(data, 12),
    )


def read_block_header(data: bytes, offset: int) -> tuple[int, int, int, int]:
    """Parse block header at offset (31 bytes). Returns (payload_size, block_size, next_block, bytes_consumed)."""
    if offset + BLOCK_HEADER_SIZE > len(data):
        raise ValueError("Data shorter than block header")
    if data[offset : offset + 2] != b"\x0d\x0a":
        raise ValueError("Block header must start with CRLF")
    payload_size = _read_hex8(data, offset + 2)
    if data[offset + 10] != 0x20:
        raise ValueError("Expected space after payload_size")
    block_size = _read_hex8(data, offset + 11)
    if data[offset + 19] != 0x20:
        raise ValueError("Expected space after block_size")
    next_block = _read_hex8(data, offset + 20)
    if data[offset + 28] != 0x20 or data[offset + 29 : offset + 31] != b"\x0d\x0a":
        raise ValueError("Expected space and CRLF at end of block header")
    return payload_size, block_size, next_block, BLOCK_HEADER_SIZE


def read_block_chain(data: bytes, start_offset: int) -> bytes:
    """Read block chain starting at start_offset; return concatenated payload."""
    out: list[bytes] = []
    offset = start_offset
    total_payload = 0
    first_payload_size = 0

    while True:
        if offset + BLOCK_HEADER_SIZE > len(data):
            raise ValueError("Block header beyond data")
        payload_size, block_size, next_block, _ = read_block_header(data, offset)
        if total_payload == 0:
            first_payload_size = payload_size
        chunk_start = offset + BLOCK_HEADER_SIZE
        chunk_end = chunk_start + min(block_size, first_payload_size - len(b"".join(out)))
        if chunk_end > len(data):
            raise ValueError("Block content beyond data")
        out.append(data[chunk_start:chunk_end])
        # End of chain: next_block FFFFFFFF (last) or 7FFFFFFF (Kotlin SPLITTER)
        if (next_block & 0xFFFFFFFF) in (SPLITTER, 0xFFFFFFFF):
            break
        offset = next_block
        total_payload += len(out[-1])
        if len(b"".join(out)) >= first_payload_size:
            break

    return b"".join(out)


def _read_entity_name(data: bytes, header_address: int) -> str:
    """Read entity name from block at header_address. Name is UTF-16LE at offset 20, length (payload-24)."""
    if header_address + BLOCK_HEADER_SIZE > len(data):
        raise ValueError("Header block beyond data")
    payload_size, block_size, _next, _ = read_block_header(data, header_address)
    content = read_block_chain(data, header_address)
    if len(content) < NAME_CONTENT_OFFSET + NAME_CONTENT_TAIL:
        raise ValueError("Name block content too short")
    name_len = len(content) - NAME_CONTENT_OFFSET - NAME_CONTENT_TAIL
    if name_len <= 0:
        return ""
    name_bytes = content[NAME_CONTENT_OFFSET : NAME_CONTENT_OFFSET + name_len]
    return name_bytes.decode("utf-16-le", errors="replace").strip("\x00")


def read_container(data: bytes) -> dict[str, bytes]:
    """Parse HBK container and return dict entity_name -> body bytes."""
    if len(data) < CONTAINER_HEADER_SIZE:
        raise ValueError("Data too short for HBK container")
    read_container_header(data)
    toc_offset = CONTAINER_HEADER_SIZE
    toc_payload = read_block_chain(data, toc_offset)
    n = len(toc_payload) // FILE_DESCRIPTION_SIZE
    result: dict[str, bytes] = {}
    for i in range(n):
        o = i * FILE_DESCRIPTION_SIZE
        header_address = _read_int32_le(toc_payload, o)
        body_address = _read_int32_le(toc_payload, o + 4)
        reserved = _read_int32_le(toc_payload, o + 8)
        if reserved != SPLITTER:
            continue
        try:
            name = _read_entity_name(data, header_address)
        except (ValueError, UnicodeDecodeError):
            continue
        if body_address == SPLITTER or body_address == -1:
            continue
        try:
            body = read_block_chain(data, body_address)
            result[name] = body
        except (ValueError, IndexError):
            continue
    return result


def read_container_from_path(path: Path | str) -> dict[str, bytes]:
    """Read HBK file from path and return entity_name -> body bytes."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    data = path.read_bytes()
    return read_container(data)


def extract_packblock_toc_bytes(entities: dict[str, bytes]) -> bytes | None:
    """Get raw TOC bytes from PackBlock entity (ZIP with one file, decompress → UTF-8 text)."""
    raw = entities.get("PackBlock")
    if not raw:
        return None
    import io
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(raw), "r")
        names = z.namelist()
        if not names:
            return None
        return z.read(names[0])
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


def extract_filestorage_bytes(entities: dict[str, bytes]) -> bytes | None:
    """Get FileStorage entity body (ZIP archive)."""
    return entities.get("FileStorage")


def extract_book_bytes(entities: dict[str, bytes]) -> bytes | None:
    """Get Book entity body (UTF-8 text)."""
    raw = entities.get("Book")
    if raw is None:
        return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None
