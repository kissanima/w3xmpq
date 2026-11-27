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

### `w3xmpq.core.objectdata` — map object data

Decodes the map's overrides on top of the base SLK tables.

| Function | Returns | Notes |
|---|---|---|
| `parse_object_data(data, kind=None, name=None)` | `ObjectData` | `kind` is `w3u`/`w3t`/`w3a`/`w3b`/`w3d`/`w3q`/`w3h`; inferred from `name` when omitted (`war3map.w3a`, `war3mapSkin.w3u`, …). Raises `ObjectDataError` on anything it cannot decode completely. |

`ObjectData` attributes:

| Attribute | Meaning |
|---|---|
| `kind`, `version` | detected file kind and format version (1 or 2) |
| `original`, `custom` | lists of `{original_id, custom_id, mods}` |
| `objects` | `original + custom` |
| `modification_count` | total modifications across all objects |
| `trailing`, `complete` | bytes left unread; `complete` is `True` when `trailing == 0` |
| `verify()` | dict of counts + `complete`, suitable for `--json` |
| `find(object_id)` | objects whose original **or** custom id matches |

Each modification is `{id, type, level, column, value, object_id}` where `type`
is `"int"`/`"real"`/`"unreal"`/`"string"`, and `level`/`column` are `None` for
units, items, destructables and buffs (the format omits them for those kinds —
assuming one layout for every kind desynchronises the stream).

```python
from w3xmpq.core.objectdata import parse_object_data

od = parse_object_data(open("war3map.w3a", "rb").read(), name="war3map.w3a")
print(od.verify())                 # counts + complete
for mod in od.find("A04U")[0]["mods"]:
    print(mod["id"], mod["level"], mod["value"])
```

### `w3xmpq.core.slk` — SLK tables and editor strings

| Function | Returns | Notes |
|---|---|---|
| `read_slk(path)` | `list[dict]` | SYLK-style `.slk` (the game's data tables) as rows keyed by the header row. Raises `SlkError`. |
| `load_westrings(path)` | `dict[str, str]` | `UI/WorldEditStrings.txt` → `WESTRING_*` text. |
| `load_field_names(slk_root, kind, strings=None)` | `dict[str, str]` | modification id → English label for one object-data kind, using `METADATA_FILES`. |

`METADATA_FILES` maps each kind to the metadata table that names its fields.
Extract the inputs from `War3x.mpq` first:

```bash
w3xmpq extract War3x.mpq -o slk/ -f "MetaData"
w3xmpq extract War3x.mpq -o slk/ -f "WorldEditStrings"
```

### `w3xmpq.core.mdx2fbx` — static model export

Converts one Warcraft III `.mdx` to ASCII FBX 7.4 and a JSON sidecar. It is a
presentation converter: rest-pose vertices, normals, first UV set and texture
path references are exported; animation, skinning, texture pixels and emitters
are reported in `unresolved[]`, never guessed.

| Function | Returns | Notes |
|---|---|---|
| `extract(data, max_vertices=50000, max_indices=150000, max_geosets=128)` | `dict` | Bounded geometry plan (`w3xmpq-mdx-geometry-v1`). Exceeding a limit sets `truncated: true`. |
| `write_fbx(plan, texture_map=None)` | `str` | Deterministic FBX 7.4 ASCII text. |
| `read_archive_member(archive_path, member)` | `(bytes, resolved_member)` | Direct hash probe; slash-normalizes and resolves a bare stem to `.mdx`. Returns `(None, None)` when absent. |
| `normalise_member(member)` | `str` | Validates MPQ member paths and appends `.mdx` to a bare stem. |
| `convert_mdx_to_fbx(data, out_path, sidecar_path=None, texture_map=None, ...)` | `dict` | Writes FBX + optional sidecar and returns the report (`w3xmpq-mdx2fbx-report-v1`). |

`texture_map` is a dict mapping MDX texture paths to exported image paths;
keys are normalized so `Textures\foo.blp` and `Textures/foo.blp` both match.
Paths are written with forward slashes in FBX. Team-colour replaceable textures
are intentionally not mapped.

```python
from w3xmpq.core.mdx2fbx import read_archive_member, convert_mdx_to_fbx

data, member = read_archive_member("War3.mpq",
                                   r"Units\Human\Footman\Footman.mdx")
report = convert_mdx_to_fbx(
    data, "Footman.fbx",
    sidecar_path="Footman.fbx.json",
    texture_map={r"Textures\footman.blp": "textures/footman.png"},
    source_info={"kind": "archive-member", "archive": "War3.mpq",
                 "member": member},
)
print(report["model"]["triangle_count"], report["unresolved"])
```

The same API is re-exported at package level as `w3xmpq.convert_mdx_to_fbx`
and `w3xmpq.Mdx2FbxError`. The CLI equivalent is
`w3xmpq mdx2fbx SOURCE [MEMBER] -o OUT.fbx --json`.

### `w3xmpq.gui.model_preview_data` — 3D preview buffers

`build_preview_mesh(data, ...)` consumes the same bounded extraction and
returns flat `positions`, `normals`, `colors`, `indices` and `wire_indices`
arrays plus bounds, a camera radius and explicit `unresolved` notes. It is
Qt-free, so a headless agent can verify exactly what the GUI would draw.
`empty_preview_mesh()` is the safe zero-mesh fallback. Missing normals use a
preview-only +Z fallback and are reported; they are never written back to FBX.

The GUI consumes these buffers in `w3xmpq.gui.model_view.ModelView`. A single
click on an `MDLX`/`.mdx` row selects the Model page automatically; the
viewport supports left-drag orbit, wheel zoom, right-drag pan, wireframe and
camera reset. The **Export FBX** button calls `convert_mdx_to_fbx` on the
selected entry. Preview never writes a temporary FBX.

## Error handling

- `scan_archive` / `extract_archive` never raise on individual bad blocks —
  failures are recorded per-file with `status: "failed"` and continue.
- `extract_archive` returns a `manifest` dict; check `manifest["failed"]`
  before trusting the output.
- `rebuild_map` raises `ValueError` on unreadable input maps.
- `w3xmpq.core.mdx2fbx` raises `Mdx2FbxError` on invalid MDX chunks, unsafe
  member paths or non-triangle geosets; write errors surface as `OSError`.

## Version

```python
import w3xmpq
w3xmpq.__version__   # single-sourced from package metadata
```
