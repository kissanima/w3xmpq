#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: Qt-free preview buffers for static MDX models."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', 'src')))
sys.path.insert(0, _HERE)

from test_mdx2fbx import build_mdx  # noqa: E402
from w3xmpq.core.mdx2fbx import Mdx2FbxError  # noqa: E402
from w3xmpq.core.names import guess_name  # noqa: E402
from w3xmpq.gui.model_preview_data import (SCHEMA, build_preview_mesh,  # noqa: E402
                                           empty_preview_mesh)


class TestModelPreviewData(unittest.TestCase):
    def setUp(self):
        self.blob = build_mdx()

    def test_builds_flat_buffers(self):
        mesh = build_preview_mesh(self.blob)
        self.assertEqual(mesh['schema'], SCHEMA)
        self.assertEqual(mesh['model_name'], 'Test')
        self.assertEqual(mesh['included_geosets'], 1)
        self.assertEqual(mesh['vertex_count'], 4)
        self.assertEqual(mesh['triangle_count'], 2)
        self.assertEqual(len(mesh['positions']), 12)
        self.assertEqual(len(mesh['normals']), 12)
        self.assertEqual(len(mesh['colors']), 16)
        self.assertEqual(len(mesh['indices']), 6)
        self.assertEqual(len(mesh['wire_indices']), 12)
        self.assertEqual(mesh['indices'], [0, 1, 2, 0, 2, 3])
        self.assertGreater(mesh['radius'], 0.0)
        self.assertEqual(mesh['geoset_ranges'][0]['index_count'], 6)
        self.assertFalse(mesh['truncated'])

    def test_colours_are_deterministic(self):
        first = build_preview_mesh(self.blob)['colors']
        second = build_preview_mesh(self.blob)['colors']
        self.assertEqual(first, second)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in first))

    def test_limits_report_truncation(self):
        mesh = build_preview_mesh(self.blob, max_vertices=1)
        self.assertTrue(mesh['truncated'])
        self.assertEqual(mesh['vertex_count'], 0)
        self.assertEqual(mesh['indices'], [])

    def test_unnamed_mdx_gets_a_model_name(self):
        self.assertEqual(guess_name(self.blob[:4] + b'...', 3),
                         'model_003.mdx')

    def test_invalid_model_raises(self):
        with self.assertRaises(Mdx2FbxError):
            build_preview_mesh(b'not a model')
        empty = empty_preview_mesh('bad model')
        self.assertEqual(empty['triangle_count'], 0)
        self.assertEqual(empty['unresolved'], ['bad model'])


if __name__ == '__main__':
    unittest.main()
