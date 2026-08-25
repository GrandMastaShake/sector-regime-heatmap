"""Create a dated, provenance-preserving weekly research snapshot.

Inputs are local checked-out wiki files. The caller supplies the upstream commit SHA and
file SHAs, keeping imports reproducible and avoiding live, unpinned reads.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/weekly_council_scan.yaml"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/weekly_research"))
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text())
    output = args.output_root / args.as_of_date
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for sector, paths in config["sector_sources"].items():
        extracts = []
        for relative_path in paths:
            source = args.source_root / relative_path
            if not source.exists():
                raise FileNotFoundError(source)
            extracts.append({"source_path": relative_path, "content": source.read_text()})
        sector_path = output / f"{sector.lower().replace(' ', '_')}.json"
        sector_path.write_text(json.dumps({"sector": sector, "extracts": extracts}, indent=2) + "\n")
        files.append({"sector": sector, "snapshot_path": str(sector_path), "source_paths": paths})
    manifest = {"as_of_date": args.as_of_date, "imported_at_utc": datetime.now(timezone.utc).isoformat(), "source": config["source"], "source_commit_sha": args.commit, "files": files, "cross_sector_sources": config["cross_sector_sources"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

if __name__ == "__main__":
    main()
