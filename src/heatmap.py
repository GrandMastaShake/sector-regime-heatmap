"""Manual, explainable sector-heatmap engine.

The input payload is fully self-describing: it carries the weights and rating
bands used for the run, so a historical forecast artifact can always be
replayed exactly even after config/score_weights.yaml changes. Weights are
injected at assembly time by src/assemble_payload.py.

Every gate below exists because the previous version failed it silently.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

COMPONENTS = (
    "regime_fit",
    "breadth",
    "relative_momentum",
    "volume_confirmation",
    "macro_catalyst",
)

WEIGHT_SUM_TOLERANCE = 1e-6


def rating(score: float, bands: dict[str, float]) -> str:
    ordered = sorted(bands.items(), key=lambda kv: kv[1], reverse=True)
    for label, floor in ordered:
        if score >= floor:
            return label
    return ordered[-1][0]


def validate_weights(weights: dict[str, float], horizon: str) -> None:
    missing = [c for c in COMPONENTS if c not in weights]
    if missing:
        raise ValueError(horizon + " weights missing component(s): " + ", ".join(missing))
    if "risk_penalty_max" not in weights:
        raise ValueError(horizon + " weights missing risk_penalty_max")
    total = sum(weights[c] for c in COMPONENTS)
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            horizon + " component weights sum to " + format(total, ".4f")
            + ", not 1.0. A score of 100 on every component would top out at "
            + format(total * 100, ".1f") + " and the rating bands would be miscalibrated."
        )
    if any(weights[c] < 0 for c in COMPONENTS):
        raise ValueError(horizon + " has a negative component weight")
    if not 0 <= weights["risk_penalty_max"] <= 1:
        raise ValueError(horizon + " risk_penalty_max must be between 0 and 1")


def validate_components(components: dict, sector: str, horizon: str) -> None:
    missing = [c for c in COMPONENTS if c not in components]
    if missing:
        raise ValueError(
            sector + "/" + horizon + " is missing component(s): " + ", ".join(missing)
            + ". A missing component is a data-quality failure, not a zero."
        )
    extra = [c for c in components if c not in COMPONENTS]
    if extra:
        raise ValueError(sector + "/" + horizon + " has unknown component(s): " + ", ".join(extra))
    for c in COMPONENTS:
        v = components[c]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(sector + "/" + horizon + "/" + c + " is not numeric: " + repr(v))
        if not 0 <= v <= 100:
            raise ValueError(
                sector + "/" + horizon + "/" + c + " = " + str(v) + " is outside 0-100"
            )


def normalize_risk_penalty(raw, sector: str, horizon: str, cap: float) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ValueError(sector + "/" + horizon + " risk_penalty is not numeric: " + repr(raw))
    if raw < 0:
        raise ValueError(
            sector + "/" + horizon + " risk_penalty is negative (" + str(raw)
            + "). A risk penalty can never raise a score."
        )
    return min(float(raw), cap)


def confidence(components: dict[str, float], risk_penalty: float, why: list, risks: list) -> str:
    """Confidence is evidence-gated, not just spread-gated.

    docs/metric_definitions.md requires two independent confirmations for a
    non-neutral rating. An unsourced sector can never be high confidence.
    """
    if len(why) == 0:
        return "low"
    values = [components[c] for c in COMPONENTS]
    spread = max(values) - min(values)
    if risk_penalty >= 0.04 or spread >= 35:
        return "low"
    if len(why) < 2:
        return "medium"
    if spread >= 20 or len(risks) == 0:
        return "medium"
    return "high"


def score_sector(sector_data: dict, weights: dict[str, float], bands: dict[str, float],
                 sector: str = "sector", horizon: str = "horizon") -> dict:
    components = sector_data["components"]
    validate_components(components, sector, horizon)
    penalty_frac = normalize_risk_penalty(
        sector_data.get("risk_penalty", 0.0), sector, horizon, weights["risk_penalty_max"]
    )
    why = list(sector_data.get("why", []))
    risks = list(sector_data.get("risks", []))
    raw = sum(components[c] * weights[c] for c in COMPONENTS)
    score = round(max(0.0, min(100.0, raw - penalty_frac * 100)), 1)
    return {
        "score": score,
        "rating": rating(score, bands),
        "confidence": confidence(components, penalty_frac, why, risks),
        "components": {c: components[c] for c in COMPONENTS},
        "risk_penalty": penalty_frac,
        "risk_penalty_capped": penalty_frac < float(sector_data.get("risk_penalty", 0.0)),
        "why": why,
        "risks": risks,
    }


def render(payload: dict, scored: dict[str, dict]) -> str:
    lines = [
        "# Sector Heatmap - " + payload["as_of_date"] + " (" + payload["run_type"] + ")",
        "",
        "**Regime:** " + payload["regime"]["label"]
        + " | **Confidence:** " + payload["regime"]["confidence"],
        "",
        "| Sector | Day | Week | Month | Confidence | Why |",
        "|---|---:|---:|---:|---|---|",
    ]
    for sector in sorted(scored):
        row = scored[sector]
        reason = "; ".join(row["week"]["why"][:2]) or "No rationale logged"
        cells = []
        for h in ("day", "week", "month"):
            cells.append(str(row[h]["score"]) + " (" + row[h]["rating"] + ")")
        lines.append(
            "| " + sector + " | " + " | ".join(cells)
            + " | " + row["week"]["confidence"] + " | " + reason + " |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/forecasts"))
    parser.add_argument("--dashboard-dir", type=Path, default=Path("dashboards"))
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))

    bands = payload.get("bands")
    if not bands:
        raise ValueError(
            "Payload has no 'bands' block. Rebuild it with src/assemble_payload.py "
            "so the artifact records the bands it was scored against."
        )

    for horizon in ("day", "week", "month"):
        if horizon not in payload.get("weights", {}):
            raise ValueError("Payload weights missing horizon: " + horizon)
        validate_weights(payload["weights"][horizon], horizon)

    if not payload.get("sectors"):
        raise ValueError("Payload contains no sectors")

    scored: dict[str, dict] = {}
    for sector, data in payload["sectors"].items():
        scored[sector] = {}
        for horizon in ("day", "week", "month"):
            if horizon not in data:
                raise ValueError(sector + " is missing the '" + horizon + "' block")
            block = data[horizon]
            # The day horizon needs daily bars and the upstream feed commits
            # Friday closes only, so stage_run.py marks that block unavailable
            # rather than fabricating one. Record the reason; never score it.
            reason = block.get("unavailable")
            if reason:
                supplied = [c for c, v in (block.get("components") or {}).items()
                            if v is not None]
                if supplied:
                    raise ValueError(
                        sector + "/" + horizon + " is marked unavailable but "
                        "carries component(s) " + ", ".join(sorted(supplied))
                        + ". A horizon is either scored or it is not; "
                        "'unavailable' is not a way to skip a gate."
                    )
                scored[sector][horizon] = {
                    "score": None, "rating": "unavailable", "confidence": "none",
                    "components": block.get("components", {}),
                    "why": [], "risks": [], "unavailable": reason,
                }
                continue
            scored[sector][horizon] = score_sector(
                block, payload["weights"][horizon], bands, sector, horizon
            )

    artifact = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_input": str(args.input).replace("\\", "/"),
        "as_of_date": payload["as_of_date"],
        "run_type": payload["run_type"],
        "weights": payload["weights"],
        "bands": bands,
        "regime": payload["regime"],
        "scores": scored,
    }

    stem = payload["as_of_date"] + "_" + payload["run_type"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.dashboard_dir.mkdir(parents=True, exist_ok=True)

    forecast_path = args.output_dir / (stem + ".json")
    if forecast_path.exists():
        raise FileExistsError(
            str(forecast_path) + " already exists. Forecast artifacts are immutable; "
            "write a dated correction artifact instead (docs/manual_runbook.md)."
        )

    forecast_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n"
    )
    (args.dashboard_dir / (stem + ".md")).write_text(
        render(payload, scored), encoding="utf-8", newline="\n"
    )
    print("Wrote " + str(forecast_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
