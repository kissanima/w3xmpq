# Library API

w3xmpq is usable as a Python library. Everything lives under `w3xmpq.core`
and returns plain data structures — no globals, no side effects.

```bash
pip install w3xmpq        # or: pip install git+https://github.com/kissanima/w3xmpq
```

## Quick start

```python
from w3xmpq.core.extract import scan_archive, extract_archive

# 1. Scan an archive (recovers encrypted files, guesses names)
result = scan_archive("mymap.w3x")
for f in result["files"]:
    if f["status"] == "ok":
        print(f["name"], f["size"], f["key_hex"])

# 2. Extract everything
manifest = extract_archive("mymap.w3x", "outdir/")
```

## Core modules

### `w3xmpq.core.extract`

| Function | Returns | Notes |
|---|---|---|
| `open_archive(path)` | `(MPQArchive, io)` | Handles `.w3x` (HM3W wrapper → inner MPQ) and plain MPQ. Caller must close the second element. |
| `load_listfile(arch)` | `list[str]` | Names from `(listfile)`, if present. |
| `scan_archive(path, listfile=None)` | `dict` | Single decryption pass over all blocks. Keys: `header` (w3x metadata or None), `files` (list of per-block dicts: `index, size, csize, flags, status, key_hex, name, name_source, data`). |
| `extract_archive(path, outdir, pattern=None, verbose=False, listfile=None)` | `dict` | Writes files + `manifest.json` (SHA-256 per file). Pattern is fnmatch on guessed names. |

`listfile` accepts a list of candidate names (one per block, in order) or a
path to a text file — useful when the archive has no internal `(listfile)`
and name guessing is ambiguous.

### `w3xmpq.core.keycrack`

| Function | Returns | Notes |
|---|---|---|
| `recover_base_key(ct0, size)` | `int or None` | Known-plaintext attack on the sector offset table. `ct0` = first encrypted dword of the table, `size` = uncompressed file size. |
| `recover_named_key(name, size, offset=0)` | `int` | Deterministic key for a known name (`hash(name,'TABLE')` + FIX_KEY adjust). Fallback when the crack is inconclusive. |
| `sector_count(size, sector_size)` | `int` | Number of data sectors. |

### `w3xmpq.core.sectors`

| Function | Returns |
|---|---|
| `extract_block(arch, block, fd, name=None)` | `(data, status)` — decoded file content. `status` is `"ok"`, `"failed"`, or `"raw"` (undecodable but saved verbatim). |
| `decompress_masked(mask, body, expected=None)` | `bytes` | zlib/pkware-aware sector decode with mask-byte handling. |

### `w3xmpq.core.names`

`guess_name(data)` → best-effort filename from magic bytes and structure
(`war3map.w3u`, `war3map_script.j`, `textures/xxx.blp`, …). Returns
`(name, confidence)`.

### `w3xmpq.core.diff`

`diff_archives(path_a, path_b, with_data=False)` → dict with:

| key | meaning |
|---|---|
| `changed` | `{name, a, b, size_a, size_b}` — same recovered name, different bytes |
| `only_a` / `only_b` | entries that exist on one side only (by name, or by content when unnamed) |
| `same_named` | `{name, size, sha256}` — same name, same content |
| `added` / `removed` | entries only in B / only in A **by content** (SHA-256 multiset) |
| `common` | number of files with identical content in both |
| `meta_a` / `meta_b` | path, block count, failure count |

Matching happens twice: files are paired **by recovered name** first, so an
edited script is one `changed` row instead of one add plus one remove; the
remaining blocks are matched by content hash multiset, so identical files
at different positions still match. `with_data=True` keeps the bytes on
every returned entry (the GUI diff view needs them; the CLI does not).

### `w3xmpq.core.batch`

`batch_extract(paths, outdir, pattern=None)` → walks `.w3x/.w3m/.mpq` files,
extracts each into `outdir/<archive-stem>/`, writes `index.csv` +
`index.json`. Never raises on a bad archive — errors are recorded per entry.

### `w3xmpq.core.w3x_header`

`parse_w3x_header(fd)` → dict with `format_version`, `build_version`,
`name`, `author`, `description`, `players`, `tileset`, `width`, `height`,
`flags` (`melee` bool). Returns `None` for plain MPQs.

### `w3xmpq.core.report` — deprotection report

`build_report(scan_result)` → findings list (`script_relocated`,
`script_stub`, `missing_authoring_files`, `decoy_listfile`, …) and a
plain-English `verdict`. `render_report(report)` → human-readable string;
`build_report(..., as_json=True)` for machines.

### `w3xmpq.core.safety` — map safety scan

`scan_safety(script_text)` → severity-ranked pattern hits (Preload file I/O,
mass `ExecuteFunc`, player probing, cheat natives) plus JASS statistics.
`render_safety(report)` → human-readable string. Evidence only — no risk score.

### `w3xmpq.core.mpq_write` — rebuild (v0.3, beta)

| Function | Returns |
|---|---|
| `build_mpq(files: dict[str, bytes], archive_name=None)` | `bytes` — a standard, unencrypted MPQ v0 archive (4096-byte sectors, zlib). |
| `rebuild_map(map_path, out_path, extra_files=None)` | `dict` — reads a protected map, strips decoys, resolves the real script (prefers `Scripts\\war3map.j` over the anti-tamper stub), injects minimal `war3map.wtg/.wct/.imp` stubs and a real `(listfile)`, writes a standard MPQ that WorldEdit can open. |

`rebuild_map` is one-way: it produces a *clean editable copy*. It never
modifies the original map.

### `w3xmpq.core.codecs` (v0.3, beta)

`pkware_explode(data, out_size)` — PKWARE DCL "explode" decompression.
Beta: validated against synthetic streams and length checks; full
fuzzing against real Diablo/StarCraft archives is on the roadmap.

## Error handling

- `scan_archive` / `extract_archive` never raise on individual bad blocks —
  failures are recorded per-file with `status: "failed"` and continue.
- `extract_archive` returns a `manifest` dict; check `manifest["failed"]`
  before trusting the output.
- `rebuild_map` raises `ValueError` on unreadable input maps.

## Version

```python
import w3xmpq
w3xmpq.__version__   # single-sourced from package metadata
```
