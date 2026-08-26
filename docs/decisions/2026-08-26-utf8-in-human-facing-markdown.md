# 2026-08-26 - UTF-8 in human-facing markdown; data artifacts stay ASCII

## What changed

`scripts/preflight.py` checked that `src/`, `scripts/`, `config/` and
`README.md` contained no byte above 127. It now checks that those files are
valid UTF-8. `check_ascii` became `check_encoding`.

Nothing else about encoding moved. Every read and write still passes an
explicit `encoding="utf-8"`, and every JSON writer still passes
`ensure_ascii=True`.

## Why

Owner decision: the READMEs are the front page of both repos and reading as a
plain-text dump undersells the work. The question is what the old gate was
actually buying.

`CLAUDE.md` gives the rationale: a bare `read_text()` picks up cp1252 on
Windows and dies on the arrow and check-mark glyphs in the upstream wiki, and
it makes content hashes differ between a local run and CI. Both are real. But
the first is fixed by the explicit `encoding="utf-8"` on every call -- which is
a separate rule that stays -- and the second is about **imported wiki content**
under `data/weekly_research/`, which this gate never covered.

So for source and front-page files the ASCII requirement was belt-and-braces
over a fix already in place. Replacing it with a UTF-8 validity check keeps the
failure it can still catch -- an editor silently writing cp1252 -- and drops the
restriction that was only costing legibility.

## What did NOT change

Data artifacts. Every JSON writer keeps `ensure_ascii=True`, so a content hash
is byte-identical on Windows and in CI, and
`tests/test_import.py::test_snapshot_output_is_ascii_and_hash_is_platform_stable`
still pins it. Provenance verification compares blob SHAs; that comparison must
never depend on which machine wrote the file.

`src/heatmap.py`'s per-run dashboard markdown in `dashboards/` is also
unchanged and still ASCII. It is a dated artifact rather than a front page, and
`tests/test_heatmap.py::test_rendered_dashboard_is_ascii` continues to hold.

## The replacement invariant

The README chart aligns its columns by padding sector names, so every glyph
inside the fenced block must occupy exactly one column. Emoji are
East-Asian-width `W` and would shear the bars out of line, so the chart uses
block characters (`U+2588`, `U+2591`, `U+00B7`) and the emoji live in the
markdown table, where nothing has to line up.

`test_chart_stays_single_width_so_columns_align` walks every character inside
the fenced block and rejects any double-width one. That is the failure this
change makes possible, so it is the one now covered by a test.

Suite is 106.
