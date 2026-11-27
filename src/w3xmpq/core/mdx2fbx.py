#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""w3xmpq.core.mdx2fbx — bounded, static MDX -> FBX export.

This is an **asset presentation** converter. It reads one Warcraft III ``.mdx``
model (loose file or MPQ member) and writes an ASCII FBX 7.4 file containing
rest-pose meshes, normals, the first UV set and texture path references. It
also writes a deterministic JSON sidecar so an agent can verify exactly what
was exported without parsing FBX.

It deliberately does **not** resolve animation, skinning, material animation,
texture pixels, particle/light/ribbon emitters or shader semantics. Those stay
listed in the report's ``unresolved`` field. Nothing here opens gameplay
frames, posts commands or changes simulation state.
"""

import hashlib
import json
import math
import os
import re
import struct

from .extract import open_archive
from .sectors import extract_block

MAGIC = b"MDLX"
SCHEMA = "w3xmpq-mdx-geometry-v1"
REPORT_SCHEMA = "w3xmpq-mdx2fbx-report-v1"

DEFAULT_MAX_VERTICES = 50000
DEFAULT_MAX_INDICES = 150000
DEFAULT_MAX_GEOSETS = 128

# Geoset sub-block strides measured by Tools/mdx.py across all shipped WC3
# models. Anything outside this table stops the block walk; the converter
# never guesses a stride.
GEOSET_BLOCK_STRIDE = {
    "VRTX": 12,
    "NRMS": 12,
    "PTYP": 4,
    "PCNT": 4,
    "PVTX": 2,
    "GNDX": 1,
    "MTGC": 4,
    "MATS": 4,
    "TANG": 16,
    "SKIN": 1,
    "UVBS": 8,
}

_SAFE_MEMBER = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_\\/.- "
)

UNRESOLVED = (
    "animation and skeleton deformation are not applied; rest-pose geometry only",
    "texture pixels are not embedded; export/convert BLP files separately",
    "team-colour and team-glow replaceable textures are left to presentation",
    "particle, light, ribbon and emitter systems are not converted",
    "no screenshot parity with Warcraft III is claimed",
)


class Mdx2FbxError(Exception):
    """A model, archive member or write target cannot be converted safely."""


# -- small binary readers -------------------------------------------------

def _u32(data, at):
    if at + 4 > len(data):
        raise Mdx2FbxError("read past end at %d" % at)
    return struct.unpack_from("<I", data, at)[0]


def _i32(data, at):
    if at + 4 > len(data):
        raise Mdx2FbxError("read past end at %d" % at)
    return struct.unpack_from("<i", data, at)[0]


def _f32(data, at):
    if at + 4 > len(data):
        raise Mdx2FbxError("read past end at %d" % at)
    return struct.unpack_from("<f", data, at)[0]


def _cstr(data, at, length):
    raw = bytes(data[at:at + length])
    end = raw.find(b"\0")
    if end >= 0:
        raw = raw[:end]
    return raw.decode("latin-1")


def _chunk_table(data):
    if len(data) < 4 or data[:4] != MAGIC:
        raise Mdx2FbxError("not an MDX model (magic %r)" % data[:4])
    out = []
    pos = 4
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4].decode("latin-1")
        size = _u32(data, pos + 4)
        start = pos + 8
        if start + size > len(data):
            raise Mdx2FbxError("chunk %s at %d claims %d bytes"
                               % (tag, pos, size))
        out.append((tag, start, size))
        pos = start + size
    if pos != len(data):
        raise Mdx2FbxError("%d trailing byte(s) after last chunk"
                           % (len(data) - pos))
    return out


# -- MPQ member input -----------------------------------------------------

def normalise_member(member):
    """Normalise an MPQ model member name and resolve a bare stem to .mdx."""
    name = str(member or "").strip()
    if not name or len(name) > 260:
        raise Mdx2FbxError("member path must be 1..260 characters")
    if any(ch not in _SAFE_MEMBER for ch in name):
        raise Mdx2FbxError("member path has unsupported characters")
    parts = name.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise Mdx2FbxError("member path must not traverse directories")
    name = name.replace("/", "\\").lstrip("\\")
    leaf = name.rsplit("\\", 1)[-1]
    if "." not in leaf:
        name += ".mdx"
    return name


def read_archive_member(archive_path, member):
    """Return ``(data, resolved_member)`` for one model member, or ``(None, None)``.

    Direct hash probing avoids scanning/decrypting the whole archive. The
    original path, slash-normalised path and bare-stem ``.mdx`` form are all
    tried, in that order.
    """
    raw = str(member or "").strip()
    candidates = []
    for candidate in (raw, raw.replace("/", "\\")):
        if not candidate:
            continue
        try:
            normalised = normalise_member(candidate)
        except Mdx2FbxError:
            continue
        if normalised not in candidates:
            candidates.append(normalised)
    if not candidates:
        raise Mdx2FbxError("empty member path")

    arch = open_archive(archive_path)
    try:
        for name in candidates:
            try:
                entry = arch.get_hash_table_entry(name)
            except Exception:
                continue
            if entry is None:
                continue
            block = arch.block_table[entry.block_table_index]
            if not (block.flags & 0x80000000) or not block.archived_size:
                continue
            fd = arch.read_block_data(block)
            data = extract_block(arch, block, fd, name=name, info={})
            if data:
                return data, name
        return None, None
    finally:
        try:
            arch.file.close()
        except Exception:
            pass


# -- MDX parsing ----------------------------------------------------------

def _parse_textures(payload):
    if len(payload) % 268:
        raise Mdx2FbxError("TEXS is %d bytes, not a multiple of 268"
                           % len(payload))
    out = []
    for i in range(len(payload) // 268):
        base = i * 268
        out.append({
            "replaceable_id": _u32(payload, base),
            "path": _cstr(payload, base + 4, 260),
            "flags": _u32(payload, base + 264),
        })
    return out


def _parse_materials(payload):
    out = []
    pos = 0
    while pos < len(payload):
        if pos + 12 > len(payload):
            raise Mdx2FbxError("material header overruns at %d" % pos)
        incl = _u32(payload, pos)
        end = pos + incl
        if incl < 16 or end > len(payload):
            raise Mdx2FbxError("material at %d claims %d bytes" % (pos, incl))
        p = pos + 12
        shader = ""
        if payload[p:p + 4] != b"LAYS":
            if p + 80 > end:
                raise Mdx2FbxError("material at %d has no LAYS block" % pos)
            shader = _cstr(payload, p, 80)
            p += 80
        if payload[p:p + 4] != b"LAYS" or p + 8 > end:
            raise Mdx2FbxError("material at %d has no LAYS block" % pos)
        count = _u32(payload, p + 4)
        p += 8
        layers = []
        for _ in range(count):
            if p + 28 > end:
                raise Mdx2FbxError("layer header overruns at %d" % p)
            size = _u32(payload, p)
            if size < 28 or p + size > end:
                raise Mdx2FbxError("layer at %d claims %d bytes" % (p, size))
            layers.append({
                "filter_mode": _u32(payload, p + 4),
                "shading_flags": _u32(payload, p + 8),
                "texture_id": _u32(payload, p + 12),
                "texture_anim_id": _i32(payload, p + 16),
                "coord_id": _u32(payload, p + 20),
                "alpha": _f32(payload, p + 24),
            })
            p += size
        if p != end:
            raise Mdx2FbxError("material at %d leaves %d byte(s)"
                               % (pos, end - p))
        out.append({
            "priority": _u32(payload, pos + 4),
            "flags": _u32(payload, pos + 8),
            "shader": shader,
            "layers": layers,
        })
        pos = end
    return out


def _geoset_boundaries(payload):
    out = []
    pos = 0
    while pos < len(payload):
        if pos + 4 > len(payload):
            raise Mdx2FbxError("geoset size overruns at %d" % pos)
        incl = _u32(payload, pos)
        if incl < 8 or pos + incl > len(payload):
            raise Mdx2FbxError("geoset at %d claims %d bytes" % (pos, incl))
        out.append((pos, pos + incl))
        pos += incl
    if pos != len(payload):
        raise Mdx2FbxError("geoset table ends %d byte(s) early"
                           % (len(payload) - pos))
    return out


def _parse_geoset(payload, start, end):
    """Read one geoset's fixed-stride blocks, metadata head and first UV set."""
    p = start + 4
    vertices = []
    normals = []
    indices = []
    primitive_types = []
    primitive_counts = []
    blocks = []
    while p + 8 <= end:
        tag = bytes(payload[p:p + 4]).decode("latin-1")
        if tag == "UVAS":
            break
        stride = GEOSET_BLOCK_STRIDE.get(tag)
        if stride is None:
            break
        count = _u32(payload, p + 4)
        size = count * stride
        if p + 8 + size > end:
            raise Mdx2FbxError("geoset block %s at %d claims %d item(s)"
                               % (tag, p, count))
        body = p + 8
        if tag == "VRTX":
            vertices = list(struct.unpack_from("<%df" % (count * 3),
                                               payload, body))
        elif tag == "NRMS":
            normals = list(struct.unpack_from("<%df" % (count * 3),
                                              payload, body))
        elif tag == "PVTX":
            indices = list(struct.unpack_from("<%dH" % count,
                                              payload, body))
        elif tag == "PTYP":
            primitive_types = list(struct.unpack_from("<%dI" % count,
                                                      payload, body))
        elif tag == "PCNT":
            primitive_counts = list(struct.unpack_from("<%dI" % count,
                                                       payload, body))
        blocks.append((tag, count))
        p = body + size

    # UV blocks are located from the end: 1, 2 and 3 sets ship in WC3, so a
    # forward "first UVBS" walk can land inside the wrong block. `vertices`
    # holds floats (x, y, z), so its item count is three times the vertex
    # count; the UV block stride is per vertex.
    vertex_count = len(vertices) // 3
    uv_blobs = []
    block_size = 8 + 8 * vertex_count
    at = end
    while (vertex_count and at - block_size >= p
           and payload[at - block_size:at - block_size + 4] == b"UVBS"
           and _u32(payload, at - block_size + 4) == vertex_count):
        uv_blobs.append(payload[at - block_size + 8:at])
        at -= block_size
    uv_sets = 0
    uvs = []
    if (uv_blobs and at - 8 >= p
            and payload[at - 8:at - 4] == b"UVAS"
            and _u32(payload, at - 4) == len(uv_blobs)):
        uv_sets = len(uv_blobs)
        uvs = list(struct.unpack_from("<%df" % (vertex_count * 2),
                                      uv_blobs[0], 0))

    if primitive_types and any(kind != 4 for kind in primitive_types):
        raise Mdx2FbxError("geoset at %d is not a triangle list" % start)
    if primitive_counts and sum(primitive_counts) != len(indices):
        raise Mdx2FbxError("geoset at %d: groups count %d index(es), PVTX has "
                           "%d" % (start, sum(primitive_counts),
                                   len(indices)))
    if len(indices) % 3:
        raise Mdx2FbxError("geoset at %d has %d index(es), not triangles"
                           % (start, len(indices)))

    return {
        "blocks": blocks,
        "vertices": vertices,
        "normals": normals,
        "indices": indices,
        "uvs": uvs,
        "uv_sets": uv_sets,
        "included_uv_sets": 1 if uvs else 0,
        "material_id": _u32(payload, p) if p + 4 <= end else 0,
        "selection_group": _i32(payload, p + 4) if p + 8 <= end else 0,
    }


def _material_slots(materials, textures, material_id):
    slots = []
    if material_id >= len(materials):
        raise Mdx2FbxError("geoset names material %d of %d"
                           % (material_id, len(materials)))
    for layer in materials[material_id]["layers"]:
        texture = None
        if 0 <= layer["texture_id"] < len(textures):
            texture = textures[layer["texture_id"]]
        slots.append({
            "texture": texture["path"] if texture else "",
            "replaceable_id": texture["replaceable_id"] if texture else 0,
            "team_colour": bool(texture and texture["replaceable_id"] in (1, 2)),
            "filter_mode": layer["filter_mode"],
            "shading_flags": layer["shading_flags"],
            "alpha": round(float(layer["alpha"]), 6),
        })
    return slots


def extract(data, max_vertices=DEFAULT_MAX_VERTICES,
            max_indices=DEFAULT_MAX_INDICES,
            max_geosets=DEFAULT_MAX_GEOSETS):
    """Build a bounded static geometry plan from raw MDX bytes."""
    chunks = _chunk_table(data)
    model_name = ""
    textures = []
    materials = []
    geos_payload = None
    for tag, start, size in chunks:
        payload = data[start:start + size]
        if tag == "MODL" and size >= 80:
            model_name = _cstr(payload, 0, 80)
        elif tag == "TEXS":
            textures = _parse_textures(payload)
        elif tag == "MTLS":
            materials = _parse_materials(payload)
        elif tag == "GEOS" and geos_payload is None:
            geos_payload = payload

    boundaries = _geoset_boundaries(geos_payload) if geos_payload else []
    geosets = []
    truncated = False
    omitted_geosets = 0
    total_vertices = 0
    total_indices = 0
    bounds_min = [float("inf")] * 3
    bounds_max = [float("-inf")] * 3

    for index, (start, end) in enumerate(boundaries):
        if index >= max_geosets:
            truncated = True
            omitted_geosets += len(boundaries) - index
            break
        geo = _parse_geoset(geos_payload, start, end)
        vertex_count = len(geo["vertices"]) // 3
        if (total_vertices + vertex_count > max_vertices or
                total_indices + len(geo["indices"]) > max_indices):
            truncated = True
            omitted_geosets += len(boundaries) - index
            break
        total_vertices += vertex_count
        total_indices += len(geo["indices"])
        for i in range(0, len(geo["vertices"]), 3):
            for axis in range(3):
                value = geo["vertices"][i + axis]
                bounds_min[axis] = min(bounds_min[axis], value)
                bounds_max[axis] = max(bounds_max[axis], value)
        geosets.append({
            "index": index,
            "blocks": geo["blocks"],
            "vertices": geo["vertices"],
            "normals": geo["normals"],
            "indices": geo["indices"],
            "uvs": geo["uvs"],
            "uv_sets": geo["uv_sets"],
            "included_uv_sets": geo["included_uv_sets"],
            "material_id": geo["material_id"],
            "selection_group": geo["selection_group"],
            "texture_slots": _material_slots(materials, textures,
                                             geo["material_id"]),
        })

    if not math.isfinite(bounds_min[0]):
        bounds_min = bounds_max = [0.0, 0.0, 0.0]

    return {
        "schema": SCHEMA,
        "model": model_name,
        "source_size": len(data),
        "bounds": {
            "min": [round(value, 6) for value in bounds_min],
            "max": [round(value, 6) for value in bounds_max],
        },
        "texture_count": len(textures),
        "material_count": len(materials),
        "geoset_count": len(boundaries),
        "included_geosets": len(geosets),
        "omitted_geosets": omitted_geosets,
        "vertex_count": total_vertices,
        "triangle_count": total_indices // 3,
        "truncated": truncated,
        "geosets": geosets,
        "limits": {
            "max_vertices": max_vertices,
            "max_indices": max_indices,
            "max_geosets": max_geosets,
        },
        "unresolved": list(UNRESOLVED),
    }


# -- FBX ASCII writer -----------------------------------------------------

def _quote(value):
    text = str(value if value is not None else "")
    return '"%s"' % (text.replace("\\", "\\\\").replace('"', '\\"')
                     .replace("\r", "\\r").replace("\n", "\\n"))


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    text = "%.6f" % number
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    if "." not in text:
        text += ".0"
    return text


def _integer(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def _safe_name(value, fallback):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "")).strip("_")
    return name or fallback


def _texture_key(path):
    return str(path or "").replace("\\", "/").lower()


def _texture_map_keys(mapping):
    out = {}
    for key, value in (mapping or {}).items():
        out[_texture_key(key)] = str(value)
    return out


def _resolved_texture(slots, mapping):
    for slot in slots:
        path = str(slot.get("texture") or "")
        if not path or slot.get("team_colour"):
            continue
        mapped = mapping.get(_texture_key(path), path)
        if mapped:
            return str(mapped).replace("\\", "/")
    return ""


def _array(lines, name, values, indent, integer=False):
    values = list(values)
    fmt = _integer if integer else _number
    lines.append("%s%s: *%d {" % (indent, name, len(values)))
    for start in range(0, len(values), 12):
        chunk = values[start:start + 12]
        lines.append("%s\ta: %s"
                     % (indent, ",".join(fmt(value) for value in chunk)))
    lines.append("%s}" % indent)


def write_fbx(plan, texture_map=None):
    """Render a bounded geometry plan as deterministic ASCII FBX 7.4 text."""
    mapping = _texture_map_keys(texture_map)
    model_name = _safe_name(plan.get("model"), "model")
    geosets = plan.get("geosets", [])
    textures = []
    texture_index = {}
    for geo in geosets:
        path = _resolved_texture(geo.get("texture_slots", []), mapping)
        if path and path not in texture_index:
            texture_index[path] = len(textures) + 1
            textures.append(path)

    lines = []
    lines.append("; FBX 7.4.0 project file")
    lines.append("; Generated by w3xmpq.core.mdx2fbx")
    lines.append("; Static rest-pose geometry only")
    lines.append("; ----------------------------------------------------")
    lines.append("FBXHeaderExtension:  {")
    lines.append("\tFBXHeaderVersion: 1003")
    lines.append("\tFBXVersion: 7400")
    lines.append("\tEncryptionType: 0")
    lines.append("}")
    lines.append("GlobalSettings:  {")
    lines.append("\tVersion: 1000")
    lines.append("\tProperties70:  {")
    lines.append('\t\tP: "UpAxis", "int", "Integer", "",2')
    lines.append('\t\tP: "UpAxisSign", "int", "Integer", "",1')
    lines.append('\t\tP: "FrontAxis", "int", "Integer", "",1')
    lines.append('\t\tP: "FrontAxisSign", "int", "Integer", "",1')
    lines.append('\t\tP: "CoordAxis", "int", "Integer", "",0')
    lines.append('\t\tP: "CoordAxisSign", "int", "Integer", "",1')
    lines.append('\t\tP: "UnitScaleFactor", "double", "Number", "",1.0')
    lines.append('\t\tP: "OriginalUnitScaleFactor", "double", "Number", "",1.0')
    lines.append("\t}")
    lines.append("}")
    lines.append("Definitions:  {")
    lines.append("\tVersion: 100")
    lines.append("\tCount: 5")
    for object_type, count in (("Geometry", len(geosets)),
                               ("Model", len(geosets)),
                               ("Material", len(geosets)),
                               ("Texture", len(textures)),
                               ("Video", len(textures))):
        lines.append("\tObjectType: %s {" % _quote(object_type))
        lines.append("\t\tCount: %d" % count)
        lines.append("\t}")
    lines.append("}")
    lines.append("Objects:  {")

    for index, geo in enumerate(geosets):
        geometry_id = 100000 + index
        model_id = 200000 + index
        material_id = 300000 + index
        geo_name = "%s_geo%d" % (model_name, index)
        node_name = "%s_node%d" % (model_name, index)
        vertices = geo.get("vertices", [])
        indices = geo.get("indices", [])
        normals = geo.get("normals", [])
        uvs = geo.get("uvs", [])
        vertex_count = len(vertices) // 3
        has_uvs = len(uvs) == vertex_count * 2
        faces = []
        for at in range(0, len(indices) - 2, 3):
            faces.extend((indices[at], indices[at + 1],
                          -(int(indices[at + 2]) + 1)))

        lines.append("\tGeometry: %d, %s, \"Mesh\" {"
                     % (geometry_id, _quote("Geometry::" + geo_name)))
        lines.append("\t\tGeometryVersion: 124")
        _array(lines, "Vertices", vertices, "\t\t")
        _array(lines, "PolygonVertexIndex", faces, "\t\t", integer=True)
        if len(normals) == len(vertices):
            lines.append("\t\tLayerElementNormal: 0 {")
            lines.append("\t\t\tVersion: 101")
            lines.append('\t\t\tName: "Normals"')
            lines.append('\t\t\tMappingInformationType: "ByVertice"')
            lines.append('\t\t\tReferenceInformationType: "Direct"')
            _array(lines, "Normals", normals, "\t\t\t")
            lines.append("\t\t}")
        if has_uvs:
            lines.append("\t\tLayerElementUV: 0 {")
            lines.append("\t\t\tVersion: 101")
            lines.append('\t\t\tName: "UVMap"')
            lines.append('\t\t\tMappingInformationType: "ByVertice"')
            lines.append('\t\t\tReferenceInformationType: "Direct"')
            _array(lines, "UV", uvs, "\t\t\t")
            lines.append("\t\t}")
        lines.append("\t\tLayer: 0 {")
        lines.append("\t\t\tVersion: 100")
        if len(normals) == len(vertices):
            lines.append("\t\t\tLayerElement:  {")
            lines.append('\t\t\t\tType: "LayerElementNormal"')
            lines.append("\t\t\t\tTypedIndex: 0")
            lines.append("\t\t\t}")
        if has_uvs:
            lines.append("\t\t\tLayerElement:  {")
            lines.append('\t\t\t\tType: "LayerElementUV"')
            lines.append("\t\t\t\tTypedIndex: 0")
            lines.append("\t\t\t}")
        lines.append("\t\t}")
        lines.append("\t}")

        lines.append("\tModel: %d, %s, \"Mesh\" {"
                     % (model_id, _quote("Model::" + node_name)))
        lines.append("\t\tVersion: 232")
        lines.append("\t\tProperties70:  {")
        lines.append('\t\t\tP: "Lcl Translation", "Lcl Translation", "", "A",0.0,0.0,0.0')
        lines.append('\t\t\tP: "Lcl Rotation", "Lcl Rotation", "", "A",0.0,0.0,0.0')
        lines.append('\t\t\tP: "Lcl Scaling", "Lcl Scaling", "", "A",1.0,1.0,1.0')
        lines.append("\t\t}")
        lines.append("\t}")

        slots = geo.get("texture_slots", [])
        alpha = float(slots[0].get("alpha", 1.0)) if slots else 1.0
        lines.append("\tMaterial: %d, %s, \"\" {"
                     % (material_id, _quote("Material::" + geo_name)))
        lines.append("\t\tVersion: 102")
        lines.append('\t\tShadingModel: "phong"')
        lines.append("\t\tMultiLayer: 0")
        lines.append("\t\tProperties70:  {")
        lines.append('\t\t\tP: "DiffuseColor", "Color", "", "A",0.8,0.8,0.8')
        lines.append('\t\t\tP: "Opacity", "double", "Number", "",%s'
                     % _number(alpha))
        lines.append("\t\t}")
        lines.append("\t}")

    for path, slot in texture_index.items():
        texture_id = 400000 + slot - 1
        video_id = 500000 + slot - 1
        name = "tex%d" % slot
        lines.append("\tTexture: %d, %s, \"\" {"
                     % (texture_id, _quote("Texture::" + name)))
        lines.append('\t\tType: "TextureVideoClip"')
        lines.append("\t\tVersion: 202")
        lines.append("\t\tTextureName: %s" % _quote("Texture::" + name))
        lines.append("\t\tProperties70:  {")
        lines.append('\t\t\tP: "UVSet", "Vector4D", "", "", "UVMap"')
        lines.append("\t\t}")
        lines.append("\t\tMedia: %d" % video_id)
        lines.append("\t}")
        lines.append("\tVideo: %d, %s, \"\" {"
                     % (video_id, _quote("Video::" + name)))
        lines.append('\t\tType: "Clip"')
        lines.append("\t\tVersion: 100")
        lines.append("\t\tProperties70:  {")
        lines.append('\t\t\tP: "Path", "Path", "FileName", "U",%s'
                     % _quote(path))
        lines.append("\t\t}")
        lines.append("\t\tContent: %s" % _quote(path))
        lines.append("\t}")

    lines.append("}")
    lines.append("Connections:  {")
    for index in range(len(geosets)):
        lines.append('\tC: "OO",%d,0' % (200000 + index))
        lines.append('\tC: "OO",%d,%d' % (100000 + index, 200000 + index))
        lines.append('\tC: "OO",%d,%d' % (300000 + index, 200000 + index))
    for index, geo in enumerate(geosets):
        path = _resolved_texture(geo.get("texture_slots", []), mapping)
        slot = texture_index.get(path)
        if slot:
            lines.append('\tC: "OO",%d,%d' % (400000 + slot - 1,
                                              300000 + index))
    for slot in range(1, len(textures) + 1):
        lines.append('\tC: "OO",%d,%d' % (500000 + slot - 1,
                                          400000 + slot - 1))
    lines.append("}")
    return "\n".join(lines) + "\n"


# -- conversion entry point ----------------------------------------------

def convert_mdx_to_fbx(data, out_path, sidecar_path=None, texture_map=None,
                       max_vertices=DEFAULT_MAX_VERTICES,
                       max_indices=DEFAULT_MAX_INDICES,
                       max_geosets=DEFAULT_MAX_GEOSETS,
                       write_sidecar=True, source_info=None):
    """Convert MDX ``data`` to FBX and return a deterministic report dict."""
    plan = extract(data, max_vertices=max_vertices, max_indices=max_indices,
                   max_geosets=max_geosets)
    fbx = write_fbx(plan, texture_map=texture_map)

    out_path = str(out_path)
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(out_path, "wb") as handle:
        handle.write(fbx.encode("utf-8"))

    report = {
        "schema": REPORT_SCHEMA,
        "input": dict(source_info or {}),
        "source_size": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "output": {
            "fbx": out_path,
            "fbx_sha256": hashlib.sha256(fbx.encode("utf-8")).hexdigest(),
            "sidecar": str(sidecar_path) if write_sidecar else "",
        },
        "model": {
            "name": plan["model"],
            "bounds": plan["bounds"],
            "geoset_count": plan["geoset_count"],
            "included_geosets": plan["included_geosets"],
            "omitted_geosets": plan["omitted_geosets"],
            "vertex_count": plan["vertex_count"],
            "triangle_count": plan["triangle_count"],
            "material_count": plan["material_count"],
            "texture_count": plan["texture_count"],
        },
        "geosets": [{
            "index": geo["index"],
            "vertex_count": len(geo["vertices"]) // 3,
            "triangle_count": len(geo["indices"]) // 3,
            "material_id": geo["material_id"],
            "selection_group": geo["selection_group"],
            "uv_sets": geo["uv_sets"],
            "included_uv_sets": geo["included_uv_sets"],
            "texture_slots": geo["texture_slots"],
        } for geo in plan["geosets"]],
        "texture_map": {_texture_key(key): str(value)
                        for key, value in (texture_map or {}).items()},
        "limits": plan["limits"],
        "truncated": plan["truncated"],
        "unresolved": list(plan["unresolved"]),
    }

    if write_sidecar and sidecar_path:
        sidecar = str(sidecar_path)
        side_parent = os.path.dirname(os.path.abspath(sidecar))
        if side_parent and not os.path.isdir(side_parent):
            os.makedirs(side_parent)
        with open(sidecar, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return report


# Backwards-friendly short alias for library users.
convert = convert_mdx_to_fbx
