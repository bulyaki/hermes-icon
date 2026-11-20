"""Pure-Python Electron ASAR archive reader, patcher, and Info.plist integrity updater."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import struct
from pathlib import Path
from typing import Any

DEFAULT_BLOCK_SIZE = 4194304  # 4 MiB


def _compute_integrity(data: bytes, block_size: int = DEFAULT_BLOCK_SIZE) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    if len(data) == 0:
        blocks = [hashlib.sha256(b"").hexdigest()]
    else:
        blocks = [
            hashlib.sha256(data[i : i + block_size]).hexdigest()
            for i in range(0, len(data), block_size)
        ]
    return {
        "algorithm": "SHA256",
        "hash": digest,
        "blockSize": block_size,
        "blocks": blocks,
    }


def read_asar_header(asar_path: Path) -> tuple[dict[str, Any], bytes, int]:
    """Return ``(tree_dict, raw_header_json_bytes, payload_start)``."""
    with asar_path.open("rb") as f:
        prefix = f.read(16)
        if len(prefix) != 16:
            raise ValueError(f"Truncated ASAR header in {asar_path}")
        u0, u1, u2, str_size = struct.unpack("<IIII", prefix)
        if u0 != 4:
            raise ValueError(f"Unexpected ASAR pickle prefix u0={u0}")
        header_bytes = f.read(str_size)
        if len(header_bytes) != str_size:
            raise ValueError(f"Truncated ASAR JSON header in {asar_path}")
    payload_start = 8 + u1
    tree = json.loads(header_bytes.decode("utf-8"))
    return tree, header_bytes, payload_start


def _iter_files(node: dict[str, Any], prefix: str = ""):
    for name, entry in node.get("files", {}).items():
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from _iter_files(entry, rel)
        else:
            yield rel, entry


def _lookup_entry(tree: dict[str, Any], rel_path: str) -> dict[str, Any] | None:
    parts = [p for p in rel_path.strip("/").split("/") if p]
    cur: dict[str, Any] = tree
    for part in parts[:-1]:
        files = cur.get("files", {})
        if part not in files or "files" not in files[part]:
            return None
        cur = files[part]
    entry = cur.get("files", {}).get(parts[-1])
    if isinstance(entry, dict) and "files" not in entry:
        return entry
    return None


def patch_asar(
    asar_path: Path,
    replacements: dict[str, bytes],
    *,
    info_plist_path: Path | None = None,
) -> dict[str, Any]:
    """Replace files inside ``asar_path`` and update ``Info.plist`` ElectronAsarIntegrity.

    Handles both packed entries (rewriting payload offsets, sizes, and SHA-256
    block integrity) and ``unpacked: true`` entries (updating size and SHA-256
    integrity in the ASAR header to match files in ``app.asar.unpacked``).
    """
    tree, _, orig_payload_start = read_asar_header(asar_path)

    matched_packed: dict[str, bytes] = {}
    matched_unpacked: dict[str, bytes] = {}
    for rel, new_data in replacements.items():
        entry = _lookup_entry(tree, rel)
        if entry is None:
            continue
        if entry.get("unpacked"):
            matched_unpacked[rel] = new_data
        else:
            matched_packed[rel] = new_data

    # Update unpacked metadata
    for rel, new_data in matched_unpacked.items():
        entry = _lookup_entry(tree, rel)
        assert entry is not None
        block_size = int(entry.get("integrity", {}).get("blockSize", DEFAULT_BLOCK_SIZE))
        entry["size"] = len(new_data)
        entry["integrity"] = _compute_integrity(new_data, block_size)

    # Collect all packed entries sorted by original offset so we preserve layout
    packed_entries: list[tuple[int, str, dict[str, Any]]] = []
    for rel, entry in _iter_files(tree):
        if not entry.get("unpacked") and "offset" in entry:
            packed_entries.append((int(entry["offset"]), rel, entry))
    packed_entries.sort(key=lambda item: (item[0], item[1]))

    # Stage updated packed payload in temporary file before assembling final ASAR
    tmp_payload = asar_path.with_suffix(".payload.tmp")
    tmp_asar = asar_path.with_suffix(".asar.tmp")
    try:
        cur_offset = 0
        with asar_path.open("rb") as src, tmp_payload.open("wb") as dst:
            for orig_offset, rel, entry in packed_entries:
                if rel in matched_packed:
                    new_data = matched_packed[rel]
                    block_size = int(entry.get("integrity", {}).get("blockSize", DEFAULT_BLOCK_SIZE))
                    entry["offset"] = str(cur_offset)
                    entry["size"] = len(new_data)
                    entry["integrity"] = _compute_integrity(new_data, block_size)
                    dst.write(new_data)
                    cur_offset += len(new_data)
                else:
                    orig_size = int(entry["size"])
                    entry["offset"] = str(cur_offset)
                    if orig_size > 0:
                        src.seek(orig_payload_start + orig_offset)
                        remaining = orig_size
                        while remaining > 0:
                            chunk = src.read(min(1048576, remaining))
                            if not chunk:
                                raise EOFError(f"Unexpected EOF reading {rel} from {asar_path}")
                            dst.write(chunk)
                            remaining -= len(chunk)
                    cur_offset += orig_size

        new_header_bytes = json.dumps(tree, separators=(",", ":")).encode("utf-8")
        str_size = len(new_header_bytes)
        aligned_str_size = (str_size + 3) & ~3
        padding = b"\x00" * (aligned_str_size - str_size)
        u0 = 4
        u2 = 4 + aligned_str_size
        u1 = u2 + 4
        header_prefix = struct.pack("<IIII", u0, u1, u2, str_size)

        with tmp_asar.open("wb") as out, tmp_payload.open("rb") as payload_in:
            out.write(header_prefix)
            out.write(new_header_bytes)
            out.write(padding)
            while True:
                chunk = payload_in.read(1048576)
                if not chunk:
                    break
                out.write(chunk)

        os.replace(tmp_asar, asar_path)
    finally:
        if tmp_payload.exists():
            tmp_payload.unlink(missing_ok=True)
        if tmp_asar.exists():
            tmp_asar.unlink(missing_ok=True)

    header_sha256 = hashlib.sha256(new_header_bytes).hexdigest()

    if info_plist_path is not None and info_plist_path.exists():
        update_info_plist_asar_integrity(info_plist_path, header_sha256)

    return {
        "header_sha256": header_sha256,
        "packed_updated": len(matched_packed),
        "unpacked_updated": len(matched_unpacked),
    }


def update_info_plist_asar_integrity(info_plist_path: Path, header_sha256: str) -> None:
    with info_plist_path.open("rb") as f:
        plist_data = plistlib.load(f)
    integrity = plist_data.setdefault("ElectronAsarIntegrity", {})
    res_entry = integrity.setdefault("Resources/app.asar", {"algorithm": "SHA256"})
    res_entry["algorithm"] = "SHA256"
    res_entry["hash"] = header_sha256
    tmp = info_plist_path.with_suffix(".plist.tmp")
    with tmp.open("wb") as f:
        plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML, sort_keys=False)
    os.replace(tmp, info_plist_path)


def verify_asar_integrity(
    asar_path: Path,
    info_plist_path: Path | None = None,
    unpacked_dir: Path | None = None,
    check_paths: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Verify ASAR header hash matches Info.plist (when present) and entry integrity hashes."""
    errors: list[str] = []
    tree, header_bytes, payload_start = read_asar_header(asar_path)
    actual_header_hash = hashlib.sha256(header_bytes).hexdigest()

    if info_plist_path is not None and info_plist_path.exists():
        with info_plist_path.open("rb") as f:
            plist_data = plistlib.load(f)
        expected_header_hash = (
            plist_data.get("ElectronAsarIntegrity", {})
            .get("Resources/app.asar", {})
            .get("hash")
        )
        if actual_header_hash != expected_header_hash:
            errors.append(
                f"ASAR header SHA-256 mismatch: header={actual_header_hash} Info.plist={expected_header_hash}"
            )

    targets = check_paths or [rel for rel, _ in _iter_files(tree)]
    with asar_path.open("rb") as f:
        for rel in targets:
            entry = _lookup_entry(tree, rel)
            if entry is None:
                continue
            expected_hash = entry.get("integrity", {}).get("hash")
            expected_size = int(entry.get("size", -1))
            if entry.get("unpacked"):
                if unpacked_dir is not None:
                    ufile = unpacked_dir / rel
                    if not ufile.exists():
                        errors.append(f"Missing unpacked file: {ufile}")
                        continue
                    data = ufile.read_bytes()
                    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_hash:
                        errors.append(f"Unpacked integrity mismatch for {rel}")
            else:
                offset = int(entry["offset"])
                f.seek(payload_start + offset)
                data = f.read(expected_size)
                if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_hash:
                    errors.append(f"Packed integrity mismatch for {rel}")

    return len(errors) == 0, errors
