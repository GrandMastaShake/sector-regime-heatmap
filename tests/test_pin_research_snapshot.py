"""Pinning a weekly research snapshot.

The repo has one snapshot against a plan for weekly ones, because pinning
meant transcribing sixteen blob SHAs by hand. This is that step as a command,
so the tests care most about the refusals -- a manifest that pins the wrong
thing is worse than no manifest, since the importer will happily verify it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pin_research_snapshot as pin  # noqa: E402

CONFIG = ROOT / "config/weekly_council_scan.yaml"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def upstream(tmp_path):
    """A tiny git repo shaped like weekly-council-scan's wiki/."""
    repo = tmp_path / "upstream"
    (repo / "wiki").mkdir(parents=True)
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    for rel in pin.sources(CONFIG):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content of " + rel + "\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "wikis")
    return repo


def head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def run(argv):
    return pin.main(argv)


# -- refusals ----------------------------------------------------------------

def test_refuses_a_short_commit(tmp_path, upstream):
    with pytest.raises(SystemExit) as e:
        run(["--upstream", str(upstream), "--commit", "abc123",
             "--as-of-date", "2026-09-14",
             "--output-root", str(tmp_path / "out")])
    assert "40-char" in str(e.value)


def test_refuses_a_commit_the_checkout_does_not_have(tmp_path, upstream):
    with pytest.raises(SystemExit) as e:
        run(["--upstream", str(upstream), "--commit", "0" * 40,
             "--as-of-date", "2026-09-14",
             "--output-root", str(tmp_path / "out")])
    assert "not a commit" in str(e.value)
    assert "files you never saw" in str(e.value)


def test_refuses_a_bad_date(tmp_path, upstream):
    with pytest.raises(SystemExit) as e:
        run(["--upstream", str(upstream), "--commit", head(upstream),
             "--as-of-date", "14-09-2026",
             "--output-root", str(tmp_path / "out")])
    assert "YYYY-MM-DD" in str(e.value)


def test_refuses_to_overwrite_an_existing_manifest(tmp_path, upstream):
    out = tmp_path / "out"
    args = ["--upstream", str(upstream), "--commit", head(upstream),
            "--as-of-date", "2026-09-14", "--output-root", str(out)]
    assert run(args) == 0
    with pytest.raises(SystemExit) as e:
        run(args)
    assert "already exists" in str(e.value)
    assert run(args + ["--force"]) == 0


def test_refuses_when_a_configured_source_is_absent_at_that_commit(
        tmp_path, upstream):
    """A sector staged with no evidence is the failure this prevents."""
    git(upstream, "rm", "-q", "wiki/energy.md")
    git(upstream, "commit", "-q", "-m", "drop energy")
    with pytest.raises(SystemExit) as e:
        run(["--upstream", str(upstream), "--commit", head(upstream),
             "--as-of-date", "2026-09-14",
             "--output-root", str(tmp_path / "out")])
    assert "wiki/energy.md" in str(e.value)
    assert "no evidence" in str(e.value)


# -- output ------------------------------------------------------------------

def test_writes_every_configured_source(tmp_path, upstream):
    out = tmp_path / "out"
    run(["--upstream", str(upstream), "--commit", head(upstream),
         "--as-of-date", "2026-09-14", "--output-root", str(out)])
    doc = json.loads((out / "2026-09-14" / "source_file_shas.json")
                     .read_text(encoding="utf-8"))
    assert set(doc["files"]) == set(pin.sources(CONFIG))
    assert doc["source_commit_sha"] == head(upstream)
    assert doc["source_repository"] == "GrandMastaShake/weekly-council-scan"


def test_pinned_shas_are_the_real_git_blob_ids(tmp_path, upstream):
    out = tmp_path / "out"
    run(["--upstream", str(upstream), "--commit", head(upstream),
         "--as-of-date", "2026-09-14", "--output-root", str(out)])
    doc = json.loads((out / "2026-09-14" / "source_file_shas.json")
                     .read_text(encoding="utf-8"))
    for rel, sha in doc["files"].items():
        real = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", head(upstream) + ":" + rel],
            capture_output=True, text=True).stdout.strip()
        assert sha == real, rel


def test_manifest_is_ascii_and_lf(tmp_path, upstream):
    out = tmp_path / "out"
    run(["--upstream", str(upstream), "--commit", head(upstream),
         "--as-of-date", "2026-09-14", "--output-root", str(out)])
    raw = (out / "2026-09-14" / "source_file_shas.json").read_bytes()
    raw.decode("ascii")
    assert b"\r\n" not in raw


def test_stale_sources_travel_with_the_manifest(tmp_path, upstream):
    """Staleness recorded in the file, not just printed to one terminal."""
    out = tmp_path / "out"
    run(["--upstream", str(upstream), "--commit", head(upstream),
         "--as-of-date", "2027-01-01", "--output-root", str(out)])
    doc = json.loads((out / "2027-01-01" / "source_file_shas.json")
                     .read_text(encoding="utf-8"))
    assert doc["stale_sources"], "every wiki is months old against that date"
    assert all(e["age_days"] > pin.STALE_WARN_DAYS for e in doc["stale_sources"])


def test_fresh_sources_record_no_stale_block(tmp_path, upstream):
    out = tmp_path / "out"
    import datetime
    today = datetime.date.today().isoformat()
    run(["--upstream", str(upstream), "--commit", head(upstream),
         "--as-of-date", today, "--output-root", str(out)])
    doc = json.loads((out / today / "source_file_shas.json")
                     .read_text(encoding="utf-8"))
    assert "stale_sources" not in doc


# -- the real thing ----------------------------------------------------------

def test_reproduces_the_committed_manifest_exactly():
    """The 2026-08-24 manifest was built by hand. If this script disagrees
    with it, one of the two is wrong and it matters which."""
    committed = json.loads(
        (ROOT / "data/weekly_research/2026-08-24/source_file_shas.json")
        .read_text(encoding="utf-8"))
    upstream_repo = ROOT.parent / "weekly-council-scan"
    if not (upstream_repo / ".git").is_dir():
        pytest.skip("weekly-council-scan checkout not present")
    commit = committed["source_commit_sha"]
    if subprocess.run(["git", "-C", str(upstream_repo), "cat-file", "-t", commit],
                      capture_output=True).returncode != 0:
        pytest.skip("pinned upstream commit not fetched locally")
    for rel, sha in committed["files"].items():
        assert pin.blob_sha(upstream_repo, commit, rel) == sha, rel
