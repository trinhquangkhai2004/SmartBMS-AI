"""Verify the official RT-Batt v2 ZIP and inspect pickle opcodes without loading them."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import pickletools
import stat
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path("data/raw/rt_batt/v2/our_data.zip")
PUBLISHER = {
    "dataset_url": "https://data.mendeley.com/datasets/nsc7hnsg4s/2",
    "metadata_url": "https://data.mendeley.com/public-api/datasets/nsc7hnsg4s/files?folder_id=root&version=2",
    "doi": "10.17632/nsc7hnsg4s.2",
    "version": 2,
    "license": "CC BY 4.0",
    "size_bytes": 1188136932,
    "sha256": "071d24617153693b0d29059568525e620f6af6512acc9d00c98c7adcf15125db",
}
LIMITS = {
    "max_entries": 200,
    "max_file_bytes": 128 * 1024**2,
    "max_total_bytes": 5 * 1024**3,
    "max_expansion_ratio": 20,
}
EXPECTED_GLOBALS = {
    "builtins.slice",
    "numpy.core.multiarray._reconstruct",
    "numpy.core.multiarray.scalar",
    "numpy.dtype",
    "numpy.ndarray",
    "pandas.core.frame.DataFrame",
    "pandas.core.indexes.base.Index",
    "pandas.core.indexes.base._new_Index",
    "pandas.core.indexes.range.RangeIndex",
    "pandas.core.internals.managers.BlockManager",
}
STRING_LOADS = {"UNICODE", "SHORT_BINUNICODE", "BINUNICODE", "BINUNICODE8"}
MEMO_READS = {"GET", "BINGET", "LONG_BINGET"}
UNSUPPORTED = {
    "PUT", "BINPUT", "LONG_BINPUT", "INST", "OBJ", "EXT1", "EXT2",
    "EXT4", "PERSID", "BINPERSID", "NEXT_BUFFER", "READONLY_BUFFER",
}


def validate_directory(entries):
    if not entries or len(entries) > LIMITS["max_entries"]:
        raise ValueError("ZIP entry count outside quota")
    total = sum(entry.file_size for entry in entries)
    if total > LIMITS["max_total_bytes"]:
        raise ValueError(f"ZIP expanded size outside quota: {total}")

    paths = {}
    explicit = set()
    for entry in entries:
        name = entry.orig_filename
        path = name.removesuffix("/")
        parts = path.split("/")
        if any(
            not part
            or part in {".", ".."}
            or part.endswith((".", " "))
            or any(ord(c) < 32 or c in '\\:<>|?*"' for c in part)
            or PureWindowsPath(part).is_reserved()
            for part in parts
        ):
            raise ValueError(f"Unsafe ZIP path: {name!r}")

        is_dir = entry.is_dir()
        key = path.casefold()
        if key in explicit:
            raise ValueError(f"Duplicate ZIP path: {name!r}")
        explicit.add(key)
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            details = (prefix, depth < len(parts) or is_dir)
            previous = paths.setdefault(prefix.casefold(), details)
            if previous != details:
                raise ValueError(f"Conflicting ZIP path: {name!r}")

        mode = stat.S_IFMT(entry.external_attr >> 16)
        if mode not in {0, stat.S_IFDIR if is_dir else stat.S_IFREG}:
            raise ValueError(f"Link or special ZIP member: {name!r}")
        if entry.external_attr & 0x400:
            raise ValueError(f"ZIP member has Windows reparse attribute: {name!r}")
        if entry.flag_bits & 1 or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            raise ValueError(f"Encrypted or unsupported ZIP member: {name!r}")
        if is_dir and entry.file_size:
            raise ValueError(f"Directory contains payload: {name!r}")
        ratio = entry.file_size / max(1, entry.compress_size)
        if entry.file_size > LIMITS["max_file_bytes"] or ratio > LIMITS["max_expansion_ratio"]:
            raise ValueError(f"ZIP member exceeds expanded size or ratio quota: {name!r}")
    return total


def inspect_pickle(stream):
    counts = Counter()
    globals_seen = Counter()
    memo_strings = {}
    memo_index = 0
    recent_strings = []
    protocols = set()
    findings = set()
    for opcode, value, offset in pickletools.genops(stream):
        name = opcode.name
        counts[name] += 1
        if name in STRING_LOADS or name in MEMO_READS:
            string = value if name in STRING_LOADS else memo_strings.get(value)
            if string is None:
                recent_strings.clear()
            else:
                recent_strings = (recent_strings[-1:] + [string])
            continue
        if name == "MEMOIZE":
            if recent_strings:
                memo_strings[memo_index] = recent_strings[-1]
            memo_index += 1
            continue
        if name == "FRAME":
            continue
        if name == "STACK_GLOBAL":
            if len(recent_strings) == 2:
                globals_seen[".".join(recent_strings)] += 1
            else:
                findings.add(f"Unresolved STACK_GLOBAL at byte {offset}")
        elif name == "GLOBAL":
            globals_seen[value.replace(" ", ".", 1)] += 1
        elif name == "PROTO":
            protocols.add(value)
        elif name in UNSUPPORTED:
            findings.add(f"Unsupported opcode for static analysis: {name}")
        recent_strings.clear()

    if protocols != {4} or counts["PROTO"] != 1:
        findings.add(f"Unexpected protocol declarations: {sorted(protocols)}")
    if stream.read(1):
        findings.add("Extra bytes after STOP")
    findings.update(f"Global outside expected set: {name}" for name in globals_seen.keys() - EXPECTED_GLOBALS)
    return {
        "opcodes": dict(sorted(counts.items())),
        "globals": dict(sorted(globals_seen.items())),
        "protocols": sorted(protocols),
        "findings": sorted(findings),
    }


def inspect_member(job):
    archive_path, name = job
    try:
        with ZipFile(archive_path) as archive, archive.open(name) as stream:
            return {"member": name, **inspect_pickle(stream)}
    except (ValueError, EOFError, UnicodeError) as error:
        return {"member": name, "findings": [f"Opcode parse failed: {error}"]}


def write_json(path, payload):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def audit_archive():
    raw = ROOT / ARCHIVE
    manifest_dir = ROOT / "manifests"
    receipt = json.loads((manifest_dir / "rt_batt_download_receipt.json").read_text(encoding="utf-8-sig"))
    size = raw.stat().st_size
    with raw.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if size != PUBLISHER["size_bytes"] or sha256 != PUBLISHER["sha256"]:
        raise ValueError("Local ZIP size or SHA-256 does not match Mendeley v2")
    if size != receipt["size_bytes"] or sha256 != receipt["sha256"] or receipt["archive"] != ARCHIVE.as_posix():
        raise ValueError("Download receipt does not match local ZIP")
    read_only = not bool(raw.stat().st_mode & stat.S_IWRITE)
    if not read_only:
        raise ValueError("Raw ZIP must be read-only")

    with ZipFile(raw) as archive:
        entries = archive.infolist()
        total = validate_directory(entries)
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"ZIP CRC failed for {bad_member!r}")
        files = [entry for entry in entries if not entry.is_dir()]
        extensions = Counter(Path(entry.filename).suffix.lower() or "(none)" for entry in files)
        if not files:
            raise ValueError("ZIP contains no data files")
        members = [
            {
                "path": entry.filename,
                "kind": "directory" if entry.is_dir() else "file",
                "size_bytes": entry.file_size,
                "compressed_size_bytes": entry.compress_size,
                "crc32": f"{entry.CRC:08x}",
            }
            for entry in entries
        ]

    manifest = {
        "dataset": "RT-Batt",
        "publisher": PUBLISHER,
        "download": receipt,
        "raw_read_only": read_only,
        "source_status": "SOURCE_VERIFIED",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_checks": {
            "status": "PASS",
            "test_id": "P3-DT-01",
            "path_duplicate_link_type_quota_checks": "PASS",
            "crc_all_entries": "PASS",
            "limits": LIMITS,
            "entry_count": len(entries),
            "file_count": len(files),
            "expanded_bytes": total,
            "max_member_size_bytes": max(entry.file_size for entry in files),
            "max_expansion_ratio": max(entry.file_size / max(1, entry.compress_size) for entry in files),
            "file_extensions": dict(extensions),
        },
        "members": members,
    }
    write_json(manifest_dir / "rt_batt_source_manifest.json", manifest)
    (ROOT / "checksums.sha256").write_text(f"{sha256}  {ARCHIVE.as_posix()}\n", encoding="ascii")
    print(json.dumps(manifest["archive_checks"]), flush=True)
    return raw, sha256, [entry.filename for entry in files if Path(entry.filename).suffix.lower() in {".pkl", ".pickle"}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-pickle", action="store_true", help="Inventory pickle opcodes after ZIP validation")
    args = parser.parse_args()
    raw, sha256, pickle_names = audit_archive()
    if not args.static_pickle or not pickle_names:
        return

    with ProcessPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(inspect_member, ((raw, name) for name in pickle_names)))
    globals_seen = Counter()
    opcodes = Counter()
    for result in results:
        globals_seen.update(result.get("globals", {}))
        opcodes.update(result.get("opcodes", {}))
    flagged = sum(bool(result["findings"]) for result in results)
    summary = {
        "archive_sha256": sha256,
        "scanner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": "pickletools.genops; no object deserialization",
        "status": "P3_1_SOURCE_REVIEW_REQUIRED" if flagged else "STATIC_SCAN_COMPLETE_PENDING_REVIEW",
        "members_scanned": len(results),
        "members_flagged": flagged,
        "globals": dict(sorted(globals_seen.items())),
        "opcodes": dict(sorted(opcodes.items())),
        "members": results,
    }
    write_json(ROOT / "manifests/p3_pickle_opcode_inventory.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "members"}), flush=True)


if __name__ == "__main__":
    main()
