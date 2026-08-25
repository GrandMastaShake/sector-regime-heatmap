"""Create a dated, provenance-preserving weekly research snapshot."""
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import yaml

p = argparse.ArgumentParser()
p.add_argument('--config', type=Path, default=Path('config/weekly_council_scan.yaml'))
p.add_argument('--source-root', type=Path, required=True)
p.add_argument('--commit', required=True)
p.add_argument('--file-shas', type=Path, required=True)
p.add_argument('--as-of-date', required=True)
p.add_argument('--output-root', type=Path, default=Path('data/weekly_research'))

def main():
    a = p.parse_args(); cfg = yaml.safe_load(a.config.read_text()); shas = json.loads(a.file_shas.read_text()); out = a.output_root / a.as_of_date; out.mkdir(parents=True, exist_ok=True); sectors = []
    for sector, paths in cfg['sector_sources'].items():
        extracts = []
        for rel in paths:
            if rel not in shas: raise KeyError(f'Missing Git blob SHA: {rel}')
            content = (a.source_root / rel).read_text()
            extracts.append({'source_path': rel, 'source_file_sha': shas[rel], 'content_sha256': hashlib.sha256(content.encode()).hexdigest(), 'content': content})
        name = f"{sector.lower().replace(' ', '_')}.json"; (out / name).write_text(json.dumps({'sector': sector, 'extracts': extracts}, indent=2) + '\n'); sectors.append({'sector': sector, 'snapshot_path': name, 'source_paths': paths})
    manifest = {'as_of_date': a.as_of_date, 'imported_at_utc': datetime.now(timezone.utc).isoformat(), 'source': cfg['source'], 'source_commit_sha': a.commit, 'sectors': sectors, 'cross_sector_sources': cfg['cross_sector_sources']}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
if __name__ == '__main__': main()
