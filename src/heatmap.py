"""Manual, explainable sector-heatmap engine."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

BANDS = ((70, "favorable"), (55, "constructive"), (45, "neutral"), (30, "unfavorable"), (0, "defensive"))

def rating(score: float) -> str:
    return next(label for floor, label in BANDS if score >= floor)

def confidence(components: dict[str, float], risk_penalty: float) -> str:
    spread = max(components.values()) - min(components.values())
    if risk_penalty >= 0.04 or spread >= 35:
        return "low"
    if spread >= 20:
        return "medium"
    return "high"

def score_sector(sector: dict, weights: dict[str, float]) -> dict:
    components = sector["components"]
    raw = sum(components[name] * weights[name] for name in components)
    penalty = min(sector.get("risk_penalty", 0), weights["risk_penalty_max"]) * 100
    score = round(max(0, min(100, raw - penalty)), 1)
    return {"score": score, "rating": rating(score), "confidence": confidence(components, sector.get("risk_penalty", 0)), "components": components, "risk_penalty": sector.get("risk_penalty", 0), "why": sector.get("why", []), "risks": sector.get("risks", [])}

def render(payload: dict, scored: dict[str, dict]) -> str:
    lines = [f"# Sector Heatmap — {payload['as_of_date']} ({payload['run_type']})", "", f"**Regime:** {payload['regime']['label']} | **Confidence:** {payload['regime']['confidence']}", "", "| Sector | Day | Week | Month | Confidence | Why |", "|---|---:|---:|---:|---|---|"]
    for sector in sorted(scored):
        row = scored[sector]
        reason = "; ".join(row["week"]["why"][:2]) or "No rationale logged"
        lines.append(f"| {sector} | {row['day']['score']} ({row['day']['rating']}) | {row['week']['score']} ({row['week']['rating']}) | {row['month']['score']} ({row['month']['rating']}) | {row['week']['confidence']} | {reason} |")
    return "\n".join(lines) + "\n"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/forecasts"))
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    scored = {sector: {horizon: score_sector(data[horizon], payload["weights"][horizon]) for horizon in ("day", "week", "month")} for sector, data in payload["sectors"].items()}
    artifact = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "source_input": str(args.input), "regime": payload["regime"], "scores": scored}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{payload['as_of_date']}_{payload['run_type']}"
    (args.output_dir / f"{stem}.json").write_text(json.dumps(artifact, indent=2) + "\n")
    Path("dashboards").mkdir(exist_ok=True)
    Path(f"dashboards/{stem}.md").write_text(render(payload, scored))

if __name__ == "__main__":
    main()
