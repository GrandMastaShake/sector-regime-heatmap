"""Assemble a dated heat-map input from a base payload and sector files."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("sector_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.base.read_text())
    payload["sectors"] = {}
    for path in sorted(args.sector_dir.glob("*.json")):
        sector = json.loads(path.read_text())
        name = sector.pop("sector")
        payload["sectors"][name] = sector
    if len(payload["sectors"]) != 11:
        raise ValueError(f"Expected 11 sectors, found {len(payload['sectors'])}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
