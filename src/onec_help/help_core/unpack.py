"""Unpack .hbk: for .hbk try HBK container first (TOC + full content), then 7z, zipfile, offset, unzip, scan. Encodings: TOC and scan filenames try utf-8 then cp1251."""

import os
import struct
import subprocess
import zipfile
import zlib
from io import BytesIO
from pathlib import Path


# Таймаут 7z/unzip (секунды). From env_config.
def _unpack_timeout() -> int:
    from ..shared import env_config

    return env_config.get_unpack_timeout()


def ensure_dir(path) -> None:
    """Create directory if it does not exist."""
    os.makedirs(path, exist_ok=True)


def _try_zipfile(archive_path: Path, output_dir: Path) -> bool:
    """Try unpacking as ZIP (Python stdlib). Returns True if successful."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(output_dir)
        return True
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def _try_zipfile_from_offset(
    archive_path: Path, output_dir: Path, offset: int = 0, truncate_tail: int = 0
) -> bool:
    """Try unpacking as ZIP from byte offset (e.g. .hbk with header). truncate_tail = bytes to ignore at end."""
    try:
        with open(archive_path, "rb") as f:
            f.seek(offset)
            data = f.read()
        if truncate_tail and len(data) > truncate_tail:
            data = data[:-truncate_tail]
        if not data:
            return False
        with zipfile.ZipFile(BytesIO(data), "r") as zf:
            zf.extractall(output_dir)
        return True
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def _try_unzip(archive_path: Path, output_dir: Path) -> bool:
    """Try unpacking with unzip command. Returns True if successful."""
    result = subprocess.run(
        ["unzip", "-o", "-q", str(archive_path), "-d", str(output_dir)],
        capture_output=True,
        text=True,
        timeout=_unpack_timeout(),
    )
    return result.returncode == 0


def _decode_filename(raw: bytes) -> str:
    """Decode ZIP local header filename: try utf-8, then cp1251 (1C often uses Windows codepage)."""
    for enc in ("utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _try_zipfile_scan_local_headers(archive_path: Path, output_dir: Path) -> bool:
    """
    Fallback for embedded ZIP with corrupted EOCD (schemui/mapui .hbk).
    Scan for PK\\x03\\x04 (local file header), parse each entry, decompress, extract.
    Returns True if at least one file was extracted.
    """
    try:
        data = archive_path.read_bytes()
    except OSError:
        return False
    sig = b"PK\x03\x04"
    seen: dict[str, int] = {}
    count = 0
    i = 0
    while True:
        idx = data.find(sig, i)
        if idx < 0:
            break
        try:
            if idx + 30 > len(data):
                i = idx + 1
                continue
            comp_method = struct.unpack("<H", data[idx + 8 : idx + 10])[0]
            comp_size = struct.unpack("<I", data[idx + 18 : idx + 22])[0]
            fn_len = struct.unpack("<H", data[idx + 26 : idx + 28])[0]
            extra_len = struct.unpack("<H", data[idx + 28 : idx + 30])[0]
            if fn_len > 500 or idx + 30 + fn_len + extra_len + comp_size > len(data):
                i = idx + 1
                continue
            fn_raw = data[idx + 30 : idx + 30 + fn_len]
            fn = _decode_filename(fn_raw)
            fn = fn.replace("..", "_").replace("\\", "_").replace("/", "_").strip()
            if not fn or fn.startswith("__MACOSX"):
                i = idx + 1
                continue
            payload_start = idx + 30 + fn_len + extra_len
            payload = data[payload_start : payload_start + comp_size]
            if comp_method == 0:
                content = payload
            elif comp_method == 8:
                content = zlib.decompress(payload, -15)
            else:
                i = idx + 1
                continue
            # Handle duplicate names (e.g. two "0" entries)
            base = fn
            n = seen.get(base, 0)
            seen[base] = n + 1
            out_name = f"{base}_{n}" if n else base
            out_path = output_dir / out_name
            out_path.write_bytes(content)
            count += 1
        except (struct.error, zlib.error, UnicodeDecodeError, OSError):
            pass
        i = idx + 1
    return count > 0


def _try_hbk_container(path_to_hbk: Path, output_dir: Path) -> bool:
    """
    Try HBK binary container (FileStorage + PackBlock TOC). Returns True if extracted.
    Used first for .hbk to get full content + .toc.json when the file is a valid container.
    """
    if path_to_hbk.suffix.lower() != ".hbk":
        return False
    try:
        from .hbk_container import (
            extract_filestorage_bytes,
            extract_packblock_toc_bytes,
            read_container_from_path,
        )
        from .toc_parser import (
            parse_toc_content,
            save_toc_json,
            toc_chunks_to_flat,
        )
    except ImportError:
        return False
    try:
        entities = read_container_from_path(path_to_hbk)
        fs = extract_filestorage_bytes(entities)
        if not fs:
            return False
        with zipfile.ZipFile(BytesIO(fs), "r") as z:
            z.extractall(output_dir)
        toc_bytes = extract_packblock_toc_bytes(entities)
        if toc_bytes:
            for enc in ("utf-8", "cp1251"):
                try:
                    content = toc_bytes.decode(enc)
                    chunks = parse_toc_content(content)
                    flat = toc_chunks_to_flat(chunks)
                    if flat:
                        save_toc_json(output_dir / ".toc.json", flat)
                    break
                except (ValueError, UnicodeDecodeError):
                    continue
        return True
    except (FileNotFoundError, ValueError, OSError):
        return False


def unpack_hbk(path_to_hbk, output_dir) -> None:
    """
    Unpack .hbk (or archive): for .hbk try HBK container first (full content + TOC),
    then 7z, Python zipfile, zip from offset, unzip, scan local headers.
    Preserves full paths where the format allows.
    """
    path_to_hbk = Path(path_to_hbk).resolve()
    output_dir = Path(output_dir).resolve()
    if not path_to_hbk.is_file():
        raise FileNotFoundError(f"Archive not found: {path_to_hbk}")
    ensure_dir(output_dir)

    # For .hbk: try container first (synergy — get TOC + full FileStorage when format is container)
    if _try_hbk_container(path_to_hbk, output_dir):
        return

    def _7z_extracted() -> bool:
        """True if output_dir has at least one file (7z may return 2 but still extract)."""
        try:
            return any(output_dir.iterdir())
        except OSError:
            return False

    # 1) 7z — auto, all formats, cab, zip (mapui/schemui sometimes CAB)
    result = None
    timeout = _unpack_timeout()
    try:
        for fmt in [None, "*", "cab", "zip"]:
            cmd = ["7z", "x", str(path_to_hbk), f"-o{output_dir}", "-y"]
            if fmt:
                cmd.insert(2, f"-t{fmt}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 or _7z_extracted():
                return
    except FileNotFoundError:
        result = None

    # 2) Python zipfile (ZIP/deflate)
    if _try_zipfile(path_to_hbk, output_dir):
        return

    # 3) ZIP with header offset (some .hbk: "Headers Error", "data after end" — ZIP may start at offset)
    file_size = path_to_hbk.stat().st_size
    for skip, tail in [
        (0, 0),
        (1656, 39274),
        (1656, 0),
        (2048, 0),
        (1024, 0),
        (512, 0),
        (256, 0),
        (4096, 0),
        (8192, 0),
    ]:
        if skip < file_size and file_size - skip > tail:
            if _try_zipfile_from_offset(path_to_hbk, output_dir, offset=skip, truncate_tail=tail):
                return

    # 4) unzip command
    if _try_unzip(path_to_hbk, output_dir):
        return

    # 5) Scan for embedded ZIP with corrupted EOCD (schemui/mapui FileStorage)
    if _try_zipfile_scan_local_headers(path_to_hbk, output_dir):
        return

    err = (result.stderr or result.stdout or "").strip() if result else ""
    tried = "Tried: HBK container (first for .hbk), 7z, Python zipfile, zip from offset, unzip, scan local headers."
    if path_to_hbk.suffix.lower() == ".hbk":
        raise RuntimeError(
            f"All unpack methods failed. {tried} "
            "Try unpacking the .hbk manually (e.g. 7z x file.hbk -o./out), then use the unpacked folder. "
            f"Last 7z output: {err}"
        )
    raise RuntimeError(f"All unpack methods failed. {tried} Last 7z output: {err}")


def unpack_diag(archive_path: str | Path, output_dir: str | Path) -> None:
    """Diagnostic: try each unpack method and print results. Use when unpack fails."""
    path = Path(archive_path).resolve()
    out = Path(output_dir).resolve()
    if not path.is_file():
        print(f"File not found: {path}")
        return
    print(f"File: {path} ({path.stat().st_size} bytes)")
    out.mkdir(parents=True, exist_ok=True)
    print()

    # 7z list format
    try:
        r = subprocess.run(["7z", "l", "-slt", str(path)], capture_output=True, text=True)
        print("--- 7z l -slt (format detection) ---")
        print((r.stdout or r.stderr or "(empty)")[:800])
        print()
    except FileNotFoundError:
        print("7z not found")
    except Exception as e:
        print(f"7z l error: {e}")
    print()

    # Try each 7z format
    for fmt in [None, "*", "cab", "zip"]:
        try:
            cmd = ["7z", "x", str(path), f"-o{out}", "-y"]
            if fmt:
                cmd.insert(2, f"-t{fmt}")
            r = subprocess.run(cmd, capture_output=True, text=True)
            ok = r.returncode == 0 or any(out.iterdir())
            print(
                f"7z {'-t' + fmt if fmt else '(default)'}: returncode={r.returncode}, extracted={ok}"
            )
            if r.stderr:
                print(f"  stderr: {(r.stderr or '')[:300]}")
            if r.stdout and "Error" in r.stdout:
                print(f"  stdout: {(r.stdout or '')[:300]}")
            if ok:
                import shutil

                shutil.rmtree(out)
                out.mkdir(parents=True, exist_ok=True)
            print()
        except Exception as e:
            print(f"7z {fmt}: {e}\n")

    # zipfile
    try:
        ok = _try_zipfile(path, out)
        print(f"zipfile (Python): {ok}")
        if ok:
            import shutil

            shutil.rmtree(out)
            out.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"zipfile: {e}")
    print()

    # unzip
    try:
        ok = _try_unzip(path, out)
        print(f"unzip (cmd): {ok}")
        if ok:
            import shutil

            shutil.rmtree(out)
            out.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"unzip: {e}")
    print()

    # scan local headers (schemui/mapui embedded ZIP)
    try:
        ok = _try_zipfile_scan_local_headers(path, out)
        print(f"scan local headers: {ok}")
        if ok:
            import shutil

            shutil.rmtree(out)
            out.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"scan local headers: {e}")
