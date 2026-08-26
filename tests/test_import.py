"""Provenance and assembly gates."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import assemble_payload  # noqa: E402
import import_weekly_research as imp  # noqa: E402

SECTORS = sorted(
    k for k in yaml.safe_load((ROOT / "config/sector_baskets.yaml").read_text(encoding="utf-8"))
    if k not in ("version", "note")
)


def test_git_blob_sha1_matches_git():
    # `printf 'hello\n' | git hash-object --stdin` is a known fixed value.
    assert imp.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert imp.git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def make_upstream(tmp_path: Path) -> tuple[Path, dict]:
    cfg = yaml.safe_load((ROOT / "config/weekly_council_scan.yaml").read_text(encoding="utf-8"))
    root = tmp_path / "upstream"
    shas = {}
    paths = [p for ps in cfg["sector_sources"].values() for p in ps]
    paths += list(cfg.get("cross_sector_sources", []))
    for rel in paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        body = ("# " + rel + "\nArrow -> and a dash - stay UTF-8 safe.\n").encode("utf-8")
        f.write_bytes(body)
        shas[rel] = imp.git_blob_sha1(body)
    return root, shas


def write_shas(tmp_path: Path, shas: dict, commit: str, repo: str) -> Path:
    p = tmp_path / "shas.json"
    p.write_text(json.dumps(
        {"source_repository": repo, "source_commit_sha": commit, "files": shas}
    ), encoding="utf-8")
    return p


COMMIT = "b" * 40
REPO = "GrandMastaShake/weekly-council-scan"


def run_import(tmp_path, shas_path, source_root, commit=COMMIT):
    return imp.main([
        "--config", str(ROOT / "config/weekly_council_scan.yaml"),
        "--source-root", str(source_root),
        "--commit", commit,
        "--file-shas", str(shas_path),
        "--as-of-date", "2026-08-24",
        "--output-root", str(tmp_path / "out"),
    ])


# --- Bug: the script read the SHA dict at the top level, but the committed
#     file nests them under "files". Every run died on the first sector.
def test_import_reads_shas_from_the_files_key(tmp_path):
    root, shas = make_upstream(tmp_path)
    assert run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root) == 0
    out = tmp_path / "out" / "2026-08-24"
    assert (out / "manifest.json").is_file()
    assert (out / "technology.json").is_file()


# --- Bug: SHAs were recorded but never verified against the actual bytes.
def test_tampered_source_file_aborts_the_import(tmp_path):
    root, shas = make_upstream(tmp_path)
    (root / "wiki/tech.md").write_bytes(b"# tech\nsomeone edited this\n")
    with pytest.raises(ValueError, match="Provenance mismatch"):
        run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)


def test_commit_sha_mismatch_aborts_the_import(tmp_path):
    root, shas = make_upstream(tmp_path)
    p = write_shas(tmp_path, shas, COMMIT, REPO)
    with pytest.raises(ValueError, match="Commit SHA mismatch"):
        run_import(tmp_path, p, root, commit="c" * 40)


def test_wrong_source_repository_aborts_the_import(tmp_path):
    root, shas = make_upstream(tmp_path)
    p = write_shas(tmp_path, shas, COMMIT, "someone-else/other-repo")
    with pytest.raises(ValueError, match="Source repository mismatch"):
        run_import(tmp_path, p, root)


def test_missing_source_file_aborts_the_import(tmp_path):
    root, shas = make_upstream(tmp_path)
    (root / "wiki/energy.md").unlink()
    with pytest.raises(FileNotFoundError, match="energy.md"):
        run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)


def test_extra_pinned_file_that_nothing_references_aborts(tmp_path):
    root, shas = make_upstream(tmp_path)
    shas["wiki/orphan.md"] = "a" * 40
    with pytest.raises(ValueError, match="no config source list references"):
        run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)


# --- Bug: cross_sector_sources were listed in config but never snapshotted.
def test_cross_sector_sources_are_snapshotted(tmp_path):
    root, shas = make_upstream(tmp_path)
    run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)
    out = tmp_path / "out" / "2026-08-24"
    assert (out / "cross_sector.json").is_file()
    roles = {f["role"] for f in json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"]}
    assert roles == {"sector", "cross_sector"}


# --- Bug: the manifest violated config/weekly_research_manifest.schema.json,
#     which requires "files"; the script only wrote "sectors".
def test_manifest_satisfies_its_own_schema(tmp_path):
    root, shas = make_upstream(tmp_path)
    run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)
    manifest = json.loads(
        (tmp_path / "out/2026-08-24/manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "config/weekly_research_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(manifest, schema)


# --- Bug: read_text()/write_text() used the platform default encoding, so a
#     Windows run crashed on the arrow and check-mark glyphs in the wiki, and
#     any content hash it did produce would differ from the Linux runner's.
def test_snapshot_output_is_ascii_and_hash_is_platform_stable(tmp_path):
    root, shas = make_upstream(tmp_path)
    run_import(tmp_path, write_shas(tmp_path, shas, COMMIT, REPO), root)
    tech = (tmp_path / "out/2026-08-24/technology.json").read_bytes()
    tech.decode("ascii")  # ensure_ascii=True keeps artifacts portable
    body = json.loads(tech.decode("ascii"))
    assert body["extracts"][0]["content_sha256"]
    assert body["extracts"][0]["content_bytes"] > 0
