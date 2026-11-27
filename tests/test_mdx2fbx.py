#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: bounded MDX -> FBX export (core.mdx2fbx + CLI)."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'src'))
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.join(_HERE, 'fixtures'))

import gen_synth  # noqa: E402
from w3xmpq.core.mdx2fbx import (Mdx2FbxError, convert_mdx_to_fbx,  # noqa: E402
                                 extract, normalise_member,
                                 read_archive_member, write_fbx)


def _chunk(tag, payload):
    return tag.encode("ascii") + struct.pack("<I", len(payload)) + payload


def build_mdx():
    """One geoset, 4 vertices, 2 triangles, 1 UV set, 1 texture."""
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    normals = [(0.0, 0.0, 1.0)] * 4
    indices = [0, 1, 2, 0, 2, 3]
    uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5)]

    blocks = b"".join([
        b"VRTX" + struct.pack("<I", len(vertices))
        + struct.pack("<%df" % (len(vertices) * 3),
                      *[v for xyz in vertices for v in xyz]),
        b"NRMS" + struct.pack("<I", len(normals))
        + struct.pack("<%df" % (len(normals) * 3),
                      *[v for xyz in normals for v in xyz]),
        b"PTYP" + struct.pack("<II", 1, 4),
        b"PCNT" + struct.pack("<II", 1, len(indices)),
        b"PVTX" + struct.pack("<I", len(indices))
        + struct.pack("<%dH" % len(indices), *indices),
    ])
    meta = struct.pack("<II", 0, 0)       # material 0, selection group 0
    uvas = b"UVAS" + struct.pack("<I", 1)
    uvbs = b"UVBS" + struct.pack("<I", len(vertices)) \
        + struct.pack("<%df" % (len(vertices) * 2),
                      *[v for uv in uvs for v in uv])
    incl = 4 + len(blocks) + len(meta) + len(uvas) + len(uvbs)
    geos = struct.pack("<I", incl) + blocks + meta + uvas + uvbs

    modl = (b"Test" + b"\0" * 76 + b"\0" * 260
            + struct.pack("<f", 1.0)
            + struct.pack("<3f", 0.0, 0.0, 0.0)
            + struct.pack("<3f", 1.0, 1.0, 1.0)
            + struct.pack("<I", 0))
    texs = (struct.pack("<I", 0)
            + b"Textures\\test.blp".ljust(260, b"\0")
            + struct.pack("<I", 0))
    layer = struct.pack("<IIIIIIf", 28, 0, 0, 0, 0xFFFFFFFF, 0, 1.0)
    mat = struct.pack("<III", 48, 0, 0) + b"LAYS" \
        + struct.pack("<I", 1) + layer

    return b"MDLX" + b"".join([
        _chunk("VERS", struct.pack("<I", 800)),
        _chunk("MODL", modl),
        _chunk("TEXS", texs),
        _chunk("MTLS", mat),
        _chunk("GEOS", geos),
    ])


def _run_cli(args):
    env = dict(os.environ)
    env['PYTHONPATH'] = _SRC + os.pathsep + env.get('PYTHONPATH', '')
    return subprocess.run([sys.executable, '-m', 'w3xmpq'] + args,
                          capture_output=True, text=True, env=env)


class TestMdx2Fbx(unittest.TestCase):
    def setUp(self):
        self.blob = build_mdx()

    def test_extract_reads_geometry_material_and_uvs(self):
        plan = extract(self.blob)
        self.assertEqual(plan['schema'], 'w3xmpq-mdx-geometry-v1')
        self.assertEqual(plan['geoset_count'], 1)
        self.assertEqual(plan['vertex_count'], 4)
        self.assertEqual(plan['triangle_count'], 2)
        self.assertEqual(plan['included_geosets'], 1)
        self.assertFalse(plan['truncated'])
        geo = plan['geosets'][0]
        self.assertEqual(geo['indices'], [0, 1, 2, 0, 2, 3])
        self.assertEqual(geo['uv_sets'], 1)
        self.assertEqual(len(geo['uvs']), 8)
        self.assertEqual(geo['texture_slots'][0]['texture'],
                         'Textures\\test.blp')
        self.assertFalse(geo['texture_slots'][0]['team_colour'])

    def test_fbx_has_triangles_normals_uvs_and_texture(self):
        text = write_fbx(extract(self.blob))
        self.assertIn('FBXVersion: 7400', text)
        self.assertIn('Vertices: *12', text)
        self.assertIn('PolygonVertexIndex: *6', text)
        self.assertIn('0,1,-3', text)
        self.assertIn('0,2,-4', text)
        self.assertIn('LayerElementNormal: 0', text)
        self.assertIn('LayerElementUV: 0', text)
        self.assertIn('Textures/test.blp', text)
        self.assertIn('Connections:  {', text)

    def test_texture_map_and_sidecar_are_deterministic(self):
        mapping = {'Textures\\test.blp': 'textures/test.png'}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'test.fbx')
            side = os.path.join(tmp, 'test.fbx.json')
            report = convert_mdx_to_fbx(
                self.blob, out, sidecar_path=side, texture_map=mapping,
                source_info={'kind': 'file', 'file': 'test.mdx'})
            with open(out, 'r', encoding='utf-8') as fh:
                text = fh.read()
            with open(side, 'r', encoding='utf-8') as fh:
                saved = json.load(fh)
            self.assertEqual(saved, report)
            self.assertIn('textures/test.png', text)
            self.assertEqual(report['schema'], 'w3xmpq-mdx2fbx-report-v1')
            self.assertEqual(report['model']['triangle_count'], 2)
            self.assertEqual(report['source_size'], len(self.blob))
            self.assertNotEqual(report['output']['fbx_sha256'], '')
            self.assertTrue(any('animation' in item
                                for item in report['unresolved']))
            again = convert_mdx_to_fbx(
                self.blob, out, sidecar_path=side, texture_map=mapping,
                source_info={'kind': 'file', 'file': 'test.mdx'})
            self.assertEqual(again, report)

    def test_limits_and_validation(self):
        with self.assertRaises(Mdx2FbxError):
            extract(b'not a model')
        limited = extract(self.blob, max_vertices=1)
        self.assertTrue(limited['truncated'])
        self.assertEqual(limited['included_geosets'], 0)
        self.assertEqual(limited['omitted_geosets'], 1)
        self.assertEqual(normalise_member('Units/Foo/Foo'),
                         'Units\\Foo\\Foo.mdx')
        with self.assertRaises(Mdx2FbxError):
            normalise_member('../Foo.mdx')

    def test_archive_member_and_cli_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, 'synth.mpq')
            spec = [dict(name='Test.mdx', data=self.blob,
                         flags=gen_synth.F_EXISTS)]
            with open(archive, 'wb') as fh:
                fh.write(gen_synth.build_archive(spec))
            data, member = read_archive_member(archive, 'Test')
            self.assertEqual(data, self.blob)
            self.assertEqual(member, 'Test.mdx')

            out = os.path.join(tmp, 'cli.fbx')
            r = _run_cli(['mdx2fbx', archive, 'Test.mdx', '-o', out,
                          '--json'])
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            self.assertEqual(report['input']['kind'], 'archive-member')
            self.assertEqual(report['input']['member'], 'Test.mdx')
            self.assertTrue(os.path.isfile(out))
            self.assertTrue(os.path.isfile(out + '.json'))


if __name__ == '__main__':
    unittest.main()
