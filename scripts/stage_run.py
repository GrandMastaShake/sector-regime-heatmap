"""Stage one manual run: panel -> metrics -> partial sector inputs + evidence.

This does everything a machine can do for a cycle and then stops. What it
cannot do is decide `regime_fit` and `macro_catalyst`. It leaves those null and
attaches, per sector, the citable evidence from the pinned research snapshot so
the judgment is grounded in verified text rather than recalled impressions.

It refuses to stage a run when the preconditions fail, rather than producing a
partial artifact that looks usable:

  - the price panel and the research snapshot must be within the same week
  - basket coverage must be adequate, or the sector is marked fail and
    assemble_payload will refuse downstream
  - the research snapshot must carry verified provenance

Nothing here writes a forecast. A forecast requires the judgment step and an
explicit heatmap.py invocation.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import compute_metrics as cm  # noqa: E402
import make_sector_inputs as msi  # noqa: E402

MAX_RESEARCH_LAG_DAYS = 7
MIN_COVERAGE = 8


def latest_snapshot(root: Path) -> tuple[str, dict]:
    dirs = [d for d in (root / "data/weekly_research").iterdir()
            if d.is_dir() and (d / "manifest.json").is_file()]
    if not dirs:
        raise SystemExit("No verified research snapshot in data/weekly_research/")
    best = max(dirs, key=lambda d: d.name)
    return best.name, json.loads((best / "manifest.json").read_text(encoding="utf-8"))


def citable(text: str, limit: int = 6) -> dict:
    """Pull the lead summary and section headings so a rationale can cite a place."""
    lead = ""
    m = re.search(r'^>\s*\*"(.+?)"\*', text, re.S | re.M)
    if m:
        lead = " ".join(m.group(1).split())
    headings = [h.strip() for h in re.findall(r"^##\s+(.+)$", text, re.M)][:limit]
    return {"lead_summary": lead[:1200], "sections": headings}


def evidence_for(root: Path, snapshot: str, sector: str) -> dict:
    fn = sector.lower().replace(" ", "_") + ".json"
    path = root / "data/weekly_research" / snapshot / fn
    if not path.is_file():
        return {"available": False, "reason": "no extract for " + sector}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for e in doc["extracts"]:
        out.append({
            "source_path": e["source_path"],
            "source_file_sha": e["source_file_sha"],
            **citable(e["content"]),
        })
    return {"available": True, "snapshot": snapshot, "extracts": out}


def cross_sector_evidence(root: Path, snapshot: str) -> dict:
    path = root / "data/weekly_research" / snapshot / "cross_sector.json"
    if not path.is_file():
        return {"available": False}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {"available": True, "snapshot": snapshot,
            "extracts": [{"source_path": e["source_path"],
                          "source_file_sha": e["source_file_sha"],
                          **citable(e["content"])} for e in doc["extracts"]]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, default=None,
                   help="where partial sector inputs land (default inputs/<as_of>)")
    p.add_argument("--as-of", default=None)
    p.add_argument("--allow-thin", action="store_true",
                   help="stage anyway when coverage is short; the files still say fail")
    a = p.parse_args(argv)

    baskets = json.loads(json.dumps(__import__("yaml").safe_load(
        (ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))))

    print("Computing metrics from " + str(a.panel))
    try:
        res = cm.compute(a.panel, baskets, a.as_of)
    except cm.PanelError as exc:
        print()
        print("REFUSING to stage -- the price panel is not usable:")
        for line in str(exc).split(". "):
            print("  " + line.strip().rstrip(".") + ".")
        return 2
    as_of = res["as_of"]
    print("  panel as_of " + as_of + ", " + str(res["panel_weeks"])
          + " weeks, basis " + res["adjustment_basis"])

    snapshot, manifest = latest_snapshot(ROOT)
    if not manifest.get("provenance_verified"):
        raise SystemExit("Research snapshot " + snapshot + " is not provenance-verified")
    lag = (datetime.date.fromisoformat(snapshot) - datetime.date.fromisoformat(as_of)).days
    print("  research snapshot " + snapshot + " (upstream "
          + manifest["source_commit_sha"][:7] + "), " + str(lag) + " days after the close")
    if lag < 0:
        raise SystemExit(
            "Research snapshot " + snapshot + " predates the price close " + as_of
            + "; the research must describe the week being scored"
        )
    if lag > MAX_RESEARCH_LAG_DAYS:
        raise SystemExit(
            "Research snapshot " + snapshot + " is " + str(lag) + " days after close "
            + as_of + ", beyond the " + str(MAX_RESEARCH_LAG_DAYS)
            + "-day limit. Import a snapshot for this week."
        )

    thin = {s: b["week"]["constituents_used"] for s, b in res["sectors"].items()
            if b["week"]["constituents_used"] < MIN_COVERAGE}
    if thin and not a.allow_thin:
        print()
        print("REFUSING to stage: " + str(len(thin)) + " sector(s) below "
              + str(MIN_COVERAGE) + " of 10 constituents.")
        for s in sorted(thin):
            print("  " + s + ": " + str(thin[s]) + "/10")
        print()
        print("Run the backfill in weekly-council-scan (BACKFILL_44.md), then retry.")
        print("Use --allow-thin only to inspect; the sector files will still say fail")
        print("and assemble_payload will refuse them.")
        return 2

    out_dir = a.out_dir or (ROOT / "inputs" / as_of)
    out_dir.mkdir(parents=True, exist_ok=True)

    cross = cross_sector_evidence(ROOT, snapshot)
    (out_dir / "_cross_sector_evidence.json").write_text(
        json.dumps(cross, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8", newline="\n")

    for name, blocks in res["sectors"].items():
        doc = msi.build_sector(name, blocks, as_of, res["adjustment_basis"],
                               res["panel_weeks"])
        doc["evidence"] = evidence_for(ROOT, snapshot, name)
        doc["research_snapshot"] = {
            "as_of": snapshot,
            "source_commit_sha": manifest["source_commit_sha"],
            "provenance_verified": True,
        }
        (out_dir / (name.lower().replace(" ", "_") + ".json")).write_text(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8", newline="\n")

    print()
    print("Staged " + str(len(res["sectors"])) + " sector files in " + str(out_dir))
    print()
    print("OUTSTANDING -- for each sector, supply from the attached evidence:")
    print("  regime_fit       how the sector maps to the active regime (0-100)")
    print("  macro_catalyst   what is scheduled and what is priced (0-100)")
    print("  why              at least two sourced confirmations")
    print("  risks            what would falsify the call")
    print()
    print("Then:")
    print("  python src/assemble_payload.py examples/base_payload.json "
          + str(out_dir) + " data/inputs/" + as_of + "_manual.json")
    print("  python src/heatmap.py data/inputs/" + as_of + "_manual.json")
    print("  python scripts/render_dashboard.py")
    if res["warnings"]:
        print()
        print(str(len(res["warnings"])) + " data-quality warning(s) recorded in the "
              "sector files:")
        for w in res["warnings"][:6]:
            print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
