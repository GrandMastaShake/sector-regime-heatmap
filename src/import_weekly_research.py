"""Create a dated, provenance-preserving weekly research snapshot.

Provenance is VERIFIED, not merely recorded. Every source file's Git blob SHA-1
is recomputed from the bytes on disk and compared to the pinned manifest. A
mismatch aborts the import.

All file I/O is explicit UTF-8 with newline='' so that a run on Windows and a
run on the ubuntu-latest runner produce byte-identical output and identical
content hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_VERSION = 2


def git_blob_sha1(data: bytes) -> str:
    """Recompute Git's blob object id for raw bytes (no git binary needed)."""
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


def read_source(root: Path, rel: str) -> bytes:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError("Source file not found in pinned checkout: " + rel)
    return path.read_bytes()


def build_extract(root: Path, rel: str, pinned: dict[str, str]) -> dict:
    if rel not in pinned:
        raise KeyError("No pinned Git blob SHA recorded for source path: " + rel)
    raw = read_source(root, rel)
    actual = git_blob_sha1(raw)
    expected = pinned[rel]
    if actual != expected:
        raise ValueError(
            "Provenance mismatch for " + rel
            + "\n  pinned blob sha: " + expected
            + "\n  actual blob sha: " + actual
            + "\n  The pinned commit and the recorded SHA manifest disagree."
        )
    return {
        "source_path": rel,
        "source_file_sha": actual,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw),
        "content": raw.decode("utf-8"),
    }


def write_json(path: Path, obj: dict) -> None:
    text = json.dumps(obj, indent=2, ensure_ascii=True, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("config/weekly_council_scan.yaml"))
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--file-shas", type=Path, required=True)
    p.add_argument("--as-of-date", required=True)
    p.add_argument("--output-root", type=Path, default=Path("data/weekly_research"))
    a = p.parse_args(argv)

    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    pinned_doc = json.loads(a.file_shas.read_text(encoding="utf-8"))

    # --- Gate 1: the SHA manifest must describe the repo we think it does. ---
    expected_repo = cfg["source"]["owner"] + "/" + cfg["source"]["repo"]
    recorded_repo = pinned_doc.get("source_repository")
    if recorded_repo != expected_repo:
        raise ValueError(
            "Source repository mismatch: config expects " + expected_repo
            + " but the SHA manifest records " + str(recorded_repo)
        )

    # --- Gate 2: the pinned commit on the CLI must match the SHA manifest. ---
    recorded_commit = pinned_doc.get("source_commit_sha")
    if recorded_commit != a.commit:
        raise ValueError(
            "Commit SHA mismatch: --commit is " + a.commit
            + " but the SHA manifest records " + str(recorded_commit)
        )

    # BUG FIX: the blob SHAs live under the "files" key, not at the top level.
    pinned = pinned_doc["files"]

    out = a.output_root / a.as_of_date
    out.mkdir(parents=True, exist_ok=True)

    files: list[dict] = []
    sectors: list[dict] = []

    for sector, paths in cfg["sector_sources"].items():
        extracts = [build_extract(a.source_root, rel, pinned) for rel in paths]
        name = sector.lower().replace(" ", "_") + ".json"
        write_json(out / name, {"sector": sector, "as_of_date": a.as_of_date, "extracts": extracts})
        sectors.append({"sector": sector, "snapshot_path": name, "source_paths": list(paths)})
        for e in extracts:
            files.append({
                "source_path": e["source_path"],
                "source_file_sha": e["source_file_sha"],
                "content_sha256": e["content_sha256"],
                "snapshot_path": name,
                "role": "sector",
                "sector": sector,
            })

    # --- Cross-sector sources were previously listed but never snapshotted. ---
    cross = list(cfg.get("cross_sector_sources", []))
    if cross:
        extracts = [build_extract(a.source_root, rel, pinned) for rel in cross]
        write_json(out / "cross_sector.json", {"as_of_date": a.as_of_date, "extracts": extracts})
        for e in extracts:
            files.append({
                "source_path": e["source_path"],
                "source_file_sha": e["source_file_sha"],
                "content_sha256": e["content_sha256"],
                "snapshot_path": "cross_sector.json",
                "role": "cross_sector",
                "sector": None,
            })

    # --- Gate 3: nothing pinned may be left unused, and nothing used unpinned. ---
    used = {f["source_path"] for f in files}
    unused = sorted(set(pinned) - used)
    if unused:
        raise ValueError(
            "SHA manifest pins files that no config source list references: "
            + ", ".join(unused)
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": a.as_of_date,
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": cfg["source"],
        "source_commit_sha": a.commit,
        "provenance_verified": True,
        "files": files,
        "sectors": sectors,
        "cross_sector_sources": cross,
    }
    write_json(out / "manifest.json", manifest)

    print("Imported " + str(len(files)) + " verified source files into " + str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
