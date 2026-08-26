"""Assemble a dated heat-map input from a base payload and sector files.

This is where config/score_weights.yaml becomes authoritative. The assembler
stamps the weights and bands into the payload so the downstream forecast
artifact is self-describing and replayable. Nothing downstream re-reads config.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HORIZONS = ("day", "week", "month")


def load_expected_sectors(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return sorted(k for k in doc if k not in ("version", "note"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("sector_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--weights", type=Path, default=Path("config/score_weights.yaml"))
    parser.add_argument("--baskets", type=Path, default=Path("config/sector_baskets.yaml"))
    args = parser.parse_args(argv)

    payload = json.loads(args.base.read_text(encoding="utf-8"))
    as_of = payload.get("as_of_date")
    if not as_of or as_of == "YYYY-MM-DD":
        raise ValueError("Base payload as_of_date is still the placeholder value")

    weights_doc = yaml.safe_load(args.weights.read_text(encoding="utf-8"))
    expected = load_expected_sectors(args.baskets)

    payload["weights_config_version"] = weights_doc.get("version")
    payload["weights"] = {h: dict(weights_doc["horizons"][h]) for h in HORIZONS}
    payload["bands"] = dict(weights_doc["bands"])

    payload["sectors"] = {}
    seen_files: dict[str, str] = {}
    for path in sorted(args.sector_dir.glob("*.json")):
        sector = json.loads(path.read_text(encoding="utf-8"))
        if "sector" not in sector:
            raise ValueError(str(path) + " has no 'sector' field")
        name = sector.pop("sector")

        if name in seen_files:
            raise ValueError(
                "Sector '" + name + "' declared by two files: "
                + seen_files[name] + " and " + path.name
            )
        seen_files[name] = path.name

        if name not in expected:
            raise ValueError(
                "Sector '" + name + "' in " + path.name
                + " is not a GICS sector in " + str(args.baskets)
            )

        file_date = sector.get("as_of_date")
        if file_date != as_of:
            raise ValueError(
                path.name + " is dated " + str(file_date) + " but the run is dated "
                + as_of + ". Stale sector inputs must not be assembled into a forecast."
            )

        dq = sector.get("data_quality", {})
        if dq.get("status") not in ("pass", "warn"):
            raise ValueError(
                path.name + " data_quality.status is " + repr(dq.get("status"))
                + "; refusing to assemble a forecast from failing data."
            )

        payload["sectors"][name] = sector

    missing = sorted(set(expected) - set(payload["sectors"]))
    if missing:
        raise ValueError("Missing sector input file(s): " + ", ".join(missing))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n"
    )
    print("Assembled " + str(len(payload["sectors"])) + " sectors into " + str(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
