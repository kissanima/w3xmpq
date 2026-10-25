# Contributing

Thanks for helping improve w3xmpq!

## Ground rules

- **No copyrighted game data in the repo** — not maps, not extracted assets,
  not Blizzard MPQ fragments. Tests must use synthetic fixtures
  (`tests/fixtures/gen_synth.py` builds them from scratch).
- Read-only by design: never write to the source archive.
- Keep `src/w3xmpq/core/` free of UI imports.
- Zero required dependencies (stdlib only). Optional extras live behind
  `[extra]` names.

## Workflow

1. Fork / branch.
2. `pip install -e .`
3. `python -m unittest discover -s tests -v` must pass.
4. If you change the sector/key logic, verify against a real map *you* own
   before opening a PR, and mention the result in the description.
5. PRs: small and focused. Bug reports: include the `report`/`scan` output
   (redact any personal info) — not the map itself.

## Code style

- Python 3.9+ compatible.
- Docstrings on public functions; comments explain *why*, not *what*.
- The proven crack/sector code is intentionally verbatim in places — see the
  warning comments in `core/names.py` before "cleaning up".
