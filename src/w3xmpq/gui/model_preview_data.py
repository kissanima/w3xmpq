#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview-ready buffers for static Warcraft III models.

This module is deliberately Qt-free. It turns a bounded geometry plan from
``core.mdx2fbx.extract`` into flat arrays that a GL widget can upload. It is a
presentation adapter only: no archive writes, no FBX temp file and no claim
that the preview resolves animation, skinning, texture pixels or effects.
"""

import hashlib
import math

from ..core.mdx2fbx import (DEFAULT_MAX_GEOSETS, DEFAULT_MAX_INDICES,
                            DEFAULT_MAX_VERTICES, Mdx2FbxError, extract)

SCHEMA = "w3xmpq-model-preview-v1"

FALLBACK_PALETTE = (
    (0.78, 0.55, 0.38, 1.0),
    (0.36, 0.68, 0.78, 1.0),
    (0.58, 0.70, 0.42, 1.0),
    (0.72, 0.48, 0.70, 1.0),
    (0.76, 0.68, 0.39, 1.0),
    (0.45, 0.56, 0.82, 1.0),
)


def _stable_colour(seed):
    """Deterministic mid-bright colour from an MDX texture path."""
    digest = hashlib.sha256(str(seed or "").encode("utf-8", "replace")).digest()
    return tuple(0.35 + 0.65 * (digest[i] / 255.0) for i in range(3)) + (1.0,)


def _slot_colour(slots, geoset_index):
    """Pick one deterministic preview colour for a geoset.

    Team-colour replaceables get a fixed blue so they remain recognizable
    without pretending to resolve the game's team-colour texture.
    """
    if not slots:
        return FALLBACK_PALETTE[geoset_index % len(FALLBACK_PALETTE)]
    for slot in slots:
        if slot.get("team_colour"):
            return (0.28, 0.62, 0.86, 1.0)
    for slot in slots:
        path = slot.get("texture") or ""
        if path:
            colour = list(_stable_colour(path))
            try:
                colour[3] = max(0.15, min(1.0, float(slot.get("alpha", 1.0))))
            except (TypeError, ValueError):
                colour[3] = 1.0
            return tuple(colour)
    return FALLBACK_PALETTE[geoset_index % len(FALLBACK_PALETTE)]


def build_preview_mesh(data, max_vertices=DEFAULT_MAX_VERTICES,
                       max_indices=DEFAULT_MAX_INDICES,
                       max_geosets=DEFAULT_MAX_GEOSETS):
    """Build flat preview buffers from raw MDX ``data``.

    Returns a JSON-safe dict with ``positions`` (xyz), ``normals`` (xyz),
    ``colors`` (rgba), ``indices`` (triangle list) and ``wire_indices`` (line
    list). Missing normals use a +Z preview normal and are reported in
    ``unresolved``; they are never written back into FBX.
    """
    plan = extract(data, max_vertices=max_vertices, max_indices=max_indices,
                   max_geosets=max_geosets)
    positions = []
    normals = []
    colours = []
    indices = []
    wire_indices = []
    ranges = []
    unresolved = list(plan.get("unresolved", []))

    included = 0
    for geo in plan.get("geosets", []):
        included += 1
        vertices = geo.get("vertices", [])
        vertex_count = len(vertices) // 3
        geo_normals = geo.get("normals", [])
        has_normals = len(geo_normals) == len(vertices)
        if not has_normals:
            note = "geoset %d has no normals; preview uses a +Z fallback" \
                   % geo.get("index", included - 1)
            if note not in unresolved:
                unresolved.append(note)
        colour = _slot_colour(geo.get("texture_slots", []),
                              geo.get("index", included - 1))
        base_vertex = len(positions) // 3
        start_index = len(indices)
        start_wire = len(wire_indices)

        positions.extend(float(value) for value in vertices)
        if has_normals:
            normals.extend(float(value) for value in geo_normals)
        else:
            normals.extend([0.0, 0.0, 1.0] * vertex_count)
        for _ in range(vertex_count):
            colours.extend(colour)

        for value in geo.get("indices", []):
            indices.append(int(value) + base_vertex)
        for at in range(0, len(geo.get("indices", [])), 3):
            a, b, c = (int(value) + base_vertex
                       for value in geo["indices"][at:at + 3])
            wire_indices.extend((a, b, b, c, c, a))

        ranges.append({
            "geoset": geo.get("index", included - 1),
            "vertex_start": base_vertex,
            "vertex_count": vertex_count,
            "index_start": start_index,
            "index_count": len(indices) - start_index,
            "wire_start": start_wire,
            "wire_count": len(wire_indices) - start_wire,
            "colour": colour,
        })

    bounds = plan.get("bounds") or {}
    low = bounds.get("min") or [0.0, 0.0, 0.0]
    high = bounds.get("max") or [0.0, 0.0, 0.0]
    center = [(float(low[i]) + float(high[i])) / 2.0 for i in range(3)]
    radius = math.sqrt(sum((float(high[i]) - float(low[i])) ** 2
                           for i in range(3))) / 2.0
    if not math.isfinite(radius) or radius <= 0.0:
        radius = 1.0

    return {
        "schema": SCHEMA,
        "positions": positions,
        "normals": normals,
        "colors": colours,
        "indices": indices,
        "wire_indices": wire_indices,
        "geoset_ranges": ranges,
        "bounds": bounds,
        "center": center,
        "radius": radius,
        "model_name": plan.get("model", ""),
        "geoset_count": plan.get("geoset_count", 0),
        "included_geosets": included,
        "vertex_count": len(positions) // 3,
        "triangle_count": len(indices) // 3,
        "truncated": bool(plan.get("truncated")),
        "limits": plan.get("limits", {}),
        "unresolved": unresolved,
    }


def empty_preview_mesh(message=""):
    """A valid empty mesh used when a model cannot be decoded."""
    return {
        "schema": SCHEMA,
        "positions": [],
        "normals": [],
        "colors": [],
        "indices": [],
        "wire_indices": [],
        "geoset_ranges": [],
        "bounds": {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]},
        "center": [0.0, 0.0, 0.0],
        "radius": 1.0,
        "model_name": "",
        "geoset_count": 0,
        "included_geosets": 0,
        "vertex_count": 0,
        "triangle_count": 0,
        "truncated": False,
        "limits": {},
        "unresolved": [message] if message else [],
    }


__all__ = ["SCHEMA", "Mdx2FbxError", "build_preview_mesh",
           "empty_preview_mesh"]
