"""Pin a weekly research snapshot: write source_file_shas.json for one week.

`src/import_weekly_research.py` VERIFIES a snapshot against pinned blob SHAs
and refuses if a byte moved. It deliberately cannot generate those pins --
verifying against a manifest you just derived from the same bytes proves
nothing. Pinning is the separate, deliberate act of saying "these are the
files I am importing", and the import then proves nothing changed in between.

Doing that by hand means transcribing sixteen Git blob SHAs, and the cost
shows: the repo has exactly one snapshot (2026-08-24) against a plan for
weekly ones. This makes the pin a command.

What it does NOT do is decide whether the research is fit to import. It prints
each file's age against the as-of date and refuses on the conditions that make
a snapshot meaningless, but "are these wikis actually describing the week I am
about to score" is a judgment call and stays one.

    python scripts/pin_research_snapshot.py \\
        --upstream ../weekly-council-scan \\
        --commit <40-char sha> \\
        --as-of-date 2026-09-14

Then the existing path takes over -- Actions -> "Weekly research import", or
locally:

    python src/import_weekly_research.py --source-root ../weekly-council-scan \\
        --commit <sha> --as-of-date 2026-09-14 \\
        --file-shas data/weekly_research/2026-09-14/source_file_shas.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# A wiki older than this against the as-of date is not describing the week
# being scored. Warned, not refused -- the upstream scan legitimately skips a
# sector some weeks, and the snapshot records that rather than hiding it.
#
# Aligned with stage_run.MAX_RESEARCH_LAG_DAYS, which is the binding gate: it
# refuses a snapshot more than 7 days after the close it reads. A source older
# than that against the snapshot date cannot be describing the same week.
STALE_WARN_DAYS = 7

# The more dangerous case, and the one no age threshold catches: a snapshot
# pinned while the upstream scan is MID-RUN. On 2026-09-12 four wikis were two
# days old and twelve were six to nine days old -- pinning then would have
# mixed one week's tech, financials, healthcare and industrials with the
# previous week's everything else, and every individual age was inside any
# reasonable staleness bound.
#
# The signal is the SPREAD between oldest and newest source, not any single
# age. A completed weekly scan writes its sources within a couple of days.
MAX_SOURCE_SPREAD_DAYS = 3


def sources(config_path: Path) -> list[str]:
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths: list[str] = []
    for files in (doc.get("sector_sources") or {}).values():
        paths.extend(files)
    paths.extend(doc.get("cross_sector_sources") or [])
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def git(upstream: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(upstream), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("git " + " ".join(args) + " failed: " + r.stderr.strip())
    return r.stdout.strip()


def blob_sha(upstream: Path, commit: str, path: str) -> str | None:
    """The Git blob id of `path` at `commit`, or None if absent there."""
    r = subprocess.run(["git", "-C", str(upstream), "rev-parse",
                        commit + ":" + path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = r.stdout.strip()
    return out if SHA_RE.match(out) else None


def last_touched(upstream: Path, commit: str, path: str) -> str | None:
    out = git(upstream, "log", "-1", "--format=%cI", commit, "--", path)
    return out[:10] or None


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--upstream", type=Path, required=True,
                   help="path to a weekly-council-scan checkout")
    p.add_argument("--commit", required=True,
                   help="full 40-char upstream commit to pin")
    p.add_argument("--as-of-date", required=True, help="snapshot date YYYY-MM-DD")
    p.add_argument("--config", type=Path,
                   default=ROOT / "config/weekly_council_scan.yaml")
    p.add_argument("--output-root", type=Path,
                   default=ROOT / "data/weekly_research")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing manifest for this date")
    a = p.parse_args(argv)

    if not SHA_RE.match(a.commit):
        raise SystemExit("--commit must be a full 40-char SHA, got " + a.commit)
    try:
        as_of = datetime.date.fromisoformat(a.as_of_date)
    except ValueError:
        raise SystemExit("--as-of-date must be YYYY-MM-DD")

    # The commit must actually exist upstream, or every SHA below is a guess.
    kind = subprocess.run(["git", "-C", str(a.upstream), "cat-file", "-t",
                           a.commit], capture_output=True, text=True)
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        raise SystemExit(
            a.commit + " is not a commit in " + str(a.upstream)
            + ". Fetch it first; pinning a commit you do not have would record "
              "SHAs for files you never saw.")

    out_dir = a.output_root / a.as_of_date
    manifest_path = out_dir / "source_file_shas.json"
    if manifest_path.exists() and not a.force:
        raise SystemExit(
            str(manifest_path) + " already exists. A pinned manifest is the "
            "record of what was imported that week; rewriting it silently "
            "would unpin an existing snapshot. Pass --force only if nothing "
            "has been imported against it yet.")

    paths = sources(a.config)
    print("Pinning " + str(len(paths)) + " source file(s) at "
          + a.commit[:7] + " for " + a.as_of_date)

    files: dict = {}
    missing: list = []
    stale: list = []
    touched_dates: list = []
    for rel in paths:
        sha = blob_sha(a.upstream, a.commit, rel)
        if sha is None:
            missing.append(rel)
            print("  MISSING  " + rel)
            continue
        files[rel] = sha
        touched = last_touched(a.upstream, a.commit, rel)
        age = ((as_of - datetime.date.fromisoformat(touched)).days
               if touched else None)
        if touched:
            touched_dates.append((touched, rel))
        flag = ""
        if age is not None and age > STALE_WARN_DAYS:
            stale.append({"path": rel, "last_updated": touched,
                          "age_days": age})
            flag = "  STALE"
        print("  " + sha[:12] + "  " + rel.ljust(38)
              + (touched or "unknown") + " (" + str(age) + "d)" + flag)

    # Was the scan mid-run when this commit was made? See MAX_SOURCE_SPREAD_DAYS.
    spread = None
    if touched_dates:
        oldest, newest = min(touched_dates), max(touched_dates)
        spread = {
            "days": (datetime.date.fromisoformat(newest[0])
                     - datetime.date.fromisoformat(oldest[0])).days,
            "oldest": {"path": oldest[1], "last_updated": oldest[0]},
            "newest": {"path": newest[1], "last_updated": newest[0]},
        }

    if missing:
        raise SystemExit(
            "\n" + str(len(missing)) + " configured source file(s) do not "
            "exist at that commit: " + ", ".join(missing)
            + "\nPin a commit where the whole set exists, or correct "
              "config/weekly_council_scan.yaml. A snapshot missing a sector's "
              "only source would stage that sector with no evidence.")

    doc = {
        "source_repository": "GrandMastaShake/weekly-council-scan",
        "source_commit_sha": a.commit,
        "files": files,
    }
    if stale:
        # Recorded in the manifest, not just printed, so the staleness travels
        # with the snapshot instead of living in one terminal session.
        doc["stale_sources"] = sorted(stale, key=lambda e: -e["age_days"])
    if spread is not None:
        doc["source_age_spread"] = spread

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + "\n",
                             encoding="utf-8", newline="\n")
    print("\nWrote " + str(manifest_path))
    if stale:
        print("\n" + str(len(stale)) + " source(s) older than "
              + str(STALE_WARN_DAYS) + " days against " + a.as_of_date
              + ", recorded as stale_sources:")
        for e in stale:
            print("  " + e["path"] + "  last updated " + e["last_updated"]
                  + " (" + str(e["age_days"]) + "d)")
        print("\nThis is a warning, not a refusal. Decide whether research "
              "that old describes the week you are about to score.")

    if spread is not None and spread["days"] > MAX_SOURCE_SPREAD_DAYS:
        print("\nMID-SCAN SNAPSHOT: the sources span " + str(spread["days"])
              + " days, past the " + str(MAX_SOURCE_SPREAD_DAYS)
              + "-day bound.")
        print("  newest  " + spread["newest"]["last_updated"] + "  "
              + spread["newest"]["path"])
        print("  oldest  " + spread["oldest"]["last_updated"] + "  "
              + spread["oldest"]["path"])
        print("\nThat usually means the upstream weekly scan was still "
              "running at this commit, so the snapshot mixes one week's "
              "research for some sectors with the previous week's for "
              "others. Every individual age can look fine while the snapshot "
              "as a whole describes two different weeks. Wait for the scan to "
              "finish and pin a later commit, unless you know why a sector "
              "was skipped.")

    print("\nNext: python src/import_weekly_research.py --source-root "
          + str(a.upstream) + " \\\n        --commit " + a.commit
          + " --as-of-date " + a.as_of_date
          + " \\\n        --file-shas " + str(manifest_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
