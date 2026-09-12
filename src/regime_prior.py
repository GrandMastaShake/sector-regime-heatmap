"""The archetype prior, and where it disagrees with the tape.

The regime research says what each sector did in past episodes of a given
archetype. The daily tape says what each basket is doing now. This module puts
the two side by side and names the places they disagree.

It does not resolve them. A disagreement between a 1-4 observation prior and
five sessions of arithmetic is not a fact about which one is wrong; it is the
question `regime_fit` exists to answer, and that component is judgment on
purpose. Cycle 1 left exactly this contradiction standing in Healthcare --
prior -14 points, arithmetic rank 1 of 11 -- and wrote it into the sector's
`why` rather than resolving it. This module finds that case automatically
instead of relying on someone noticing.

Nothing here feeds a score. `src/heatmap.py` takes five components and this is
none of them.

The active archetype
--------------------
Read from the most recent forecast artifact's `regime.label`, which is where
the human declared it. Parsed, never inferred: if the label carries no
"archetype N", this module reports no prior rather than guessing one, and the
dashboard says so. Inferring the regime from price action would be a
mechanism-identification model, which the research is explicit about not
having -- and it would quietly turn a judgment call into an automated one.

The prior's age is reported with it. A prior inherited from a forecast written
five weeks ago is still the last declared regime, but the reader should be
told how old the declaration is.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

MATRIX_PATH = ROOT / "config/regime_sector_matrix.yaml"
ARCHETYPES_PATH = ROOT / "config/regime_archetypes.yaml"

# "archetype 1", "archetype 10", case-insensitive. The label is prose written
# by a human, so the parse is deliberately narrow: it matches the one phrase
# the runbook asks for and fails loudly on anything else.
ARCHETYPE_RE = re.compile(r"archetype\s+(\d{1,2})\b", re.IGNORECASE)

# Half the board apart. Eleven sectors ranked twice; a gap of six or more
# means the prior's leader is the tape's laggard or the reverse, which is a
# genuine disagreement rather than ordinary noise in the middle of the pack.
DIVERGENCE_FLAG = 6


class PriorError(RuntimeError):
    pass


def load_matrix(path: Path | None = None) -> dict:
    doc = yaml.safe_load((path or MATRIX_PATH).read_text(encoding="utf-8"))
    return doc["archetypes"]


def load_archetypes(path: Path | None = None) -> dict:
    doc = yaml.safe_load((path or ARCHETYPES_PATH).read_text(encoding="utf-8"))
    return doc


def parse_archetype(label: str | None) -> int | None:
    """Pull the archetype number out of a declared regime label."""
    if not label:
        return None
    m = ARCHETYPE_RE.search(label)
    return int(m.group(1)) if m else None


def latest_forecast(forecast_dir: Path) -> dict | None:
    """The most recent forecast artifact, or None if none is published."""
    files = sorted(p for p in forecast_dir.glob("*.json")
                   if not p.name.startswith("_"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def active_regime(forecast_dir: Path, as_of: str | None = None) -> dict:
    """What regime is declared, by whom, and how old the declaration is.

    Returns a block that always renders: `archetype` is None when nothing is
    declared or the label cannot be parsed, and `reason` says which.
    """
    fc = latest_forecast(forecast_dir)
    if fc is None:
        return {"archetype": None, "label": None, "declared_as_of": None,
                "age_days": None,
                "reason": "no forecast artifact published; the tape has no "
                          "declared regime to read a prior against"}
    label = (fc.get("regime") or {}).get("label")
    declared = fc.get("as_of_date")
    age = None
    if declared and as_of:
        age = (datetime.date.fromisoformat(as_of)
               - datetime.date.fromisoformat(declared)).days
    archetype = parse_archetype(label)
    if archetype is None:
        return {"archetype": None, "label": label, "declared_as_of": declared,
                "age_days": age,
                "reason": "the declared regime label carries no 'archetype N'; "
                          "refusing to infer one from price action"}
    return {"archetype": archetype, "label": label, "declared_as_of": declared,
            "age_days": age, "confidence": (fc.get("regime") or {}).get("confidence"),
            "reason": None}


def _rank(values: dict) -> dict:
    """Rank sectors best-to-worst, 1 = highest. Nulls are not ranked."""
    present = {k: v for k, v in values.items() if v is not None}
    order = sorted(present, key=lambda k: present[k], reverse=True)
    return {k: i + 1 for i, k in enumerate(order)}


def compare(tape: dict, archetype: int, horizon: str = "week",
            matrix: dict | None = None) -> dict:
    """Prior vs tape, per sector, with the disagreements named."""
    matrix = matrix or load_matrix()
    if archetype not in matrix:
        raise PriorError(
            "Archetype " + str(archetype) + " is not in the matrix. Known: "
            + ", ".join(str(k) for k in sorted(matrix)))
    entry = matrix[archetype]
    priors = entry["sectors"]

    live = {}
    for sector, horizons in tape["sectors"].items():
        block = horizons.get(horizon)
        live[sector] = block.get("sector_return_vs_spy_pct") if block else None

    prior_ranks = _rank(priors)
    live_ranks = _rank(live)
    n_prior, n_live = len(prior_ranks), len(live_ranks)

    rows = {}
    for sector in sorted(tape["sectors"]):
        p_excess = priors.get(sector)
        p_rank = prior_ranks.get(sector)
        l_rank = live_ranks.get(sector)
        divergence = (abs(p_rank - l_rank)
                      if p_rank is not None and l_rank is not None else None)
        flag = None
        if divergence is not None and divergence >= DIVERGENCE_FLAG:
            flag = ("prior_leader_tape_laggard" if p_rank < l_rank
                    else "prior_laggard_tape_leader")
        rows[sector] = {
            "prior_excess_points": p_excess,
            "prior_rank": p_rank,
            "prior_rank_of": n_prior,
            "tape_excess_pct": live.get(sector),
            "tape_rank": l_rank,
            "tape_rank_of": n_live,
            "rank_divergence": divergence,
            "flag": flag,
            "prior_available": p_excess is not None,
        }

    meta = load_archetypes()["archetypes"].get(archetype, {})
    return {
        "archetype": archetype,
        "archetype_name": entry.get("name"),
        "archetype_direction": entry.get("direction"),
        "archetype_n": meta.get("n"),
        "horizon": horizon,
        "divergence_flag_at": DIVERGENCE_FLAG,
        "sectors": rows,
        "contradictions": sorted(s for s, r in rows.items() if r["flag"]),
        "note": ("A prior built on " + str(meta.get("n")) + " episode"
                 + ("s" if meta.get("n") != 1 else "") + " against "
                 + str(tape.get("panel_sessions"))
                 + " sessions of arithmetic. Disagreement is the input to "
                   "regime_fit, not evidence that either side is wrong."),
    }


def likely_successors(archetype: int, archetypes: dict | None = None) -> list:
    """What this archetype has historically handed off to. n is tiny."""
    doc = archetypes or load_archetypes()
    trans = (doc.get("transitions") or {}).get(archetype) or {}
    names = doc["archetypes"]
    total = sum(trans.values())
    out = []
    for dest, count in sorted(trans.items(), key=lambda kv: -kv[1]):
        meta = names.get(dest, {})
        out.append({"archetype": dest, "name": meta.get("name"),
                    "direction": meta.get("direction"),
                    "observed": count, "of": total})
    return out
