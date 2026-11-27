# Release notes

## v1.5.0 — 2026-11-27

### Added

- `w3xmpq mdx2fbx SOURCE [MEMBER] -o OUT.fbx --json` exports bounded static
  Warcraft III MDX geometry as ASCII FBX 7.4. It accepts a loose `.mdx` file
  or a hash-probed MPQ member, resolves bare model stems to `.mdx`, supports
  texture-path remapping and writes a deterministic JSON sidecar with counts,
  hashes, limits and explicit `unresolved[]` data.
- Package API: `w3xmpq.convert_mdx_to_fbx` and `w3xmpq.Mdx2FbxError`.
- GUI: a single click on an `MDLX`/`.mdx` row opens a rest-pose 3D preview.
  The viewport supports left-drag orbit, wheel zoom, right-drag pan,
  wireframe, camera reset and an explicit **Export FBX** button. Previewing
  a model never writes a temporary FBX.
- `core.names.guess_name()` now names `MDLX` blocks `model_NNN.mdx`, so
  unnamed archive blocks are recognizable in the file table.

### Changed

- CI Linux runner is pinned to `ubuntu-24.04` because Python 3.9 has no x64
  build for Ubuntu 26.04. `actions/checkout` and `actions/setup-python` are
  upgraded to `v7` (Node 24).
- README and library API documentation cover the FBX exporter and 3D preview.

### Scope and limits

The exporter and preview are deliberately static and bounded: rest-pose
vertices, normals, first UV set and texture path references are exported.
Animation, skinning, texture pixels, shader semantics, particles, lights and
ribbons are reported in `unresolved[]`, not guessed. No screenshot parity with
Warcraft III is claimed.

### Validation

Separate `w3xmpq` suite: **151 passed / 0 failed**, 1 Pillow-only skip with
PySide6 installed. Real `Units\Human\Footman\Footman.mdx` from `War3.mpq`
exports and previews as 5 geosets / 582 vertices / 372 triangles.
