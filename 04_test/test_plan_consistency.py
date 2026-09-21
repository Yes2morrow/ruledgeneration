"""Regression tests for selected/placed counts and per-module rendering."""
import sys
import tempfile
import unittest
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '05_config_and_tools')]
from service_adapter import generate_plan_payload
from cloudrun_app.contract import to_v1_contract
from config_loader import get_module_catalog, get_site_polygon
from layout_optimizer import calculate_layout
import renderer
import numpy as np
import matplotlib.pyplot as plt


class PlanConsistencyTests(unittest.TestCase):
    def test_full_100_bed_plan_counts_match(self):
        with tempfile.TemporaryDirectory() as out:
            payload = generate_plan_payload(
                100, 30, 45, 7, selected_modules={'A': 26, 'B': 4, 'C': 2, 'D': 4},
                output_dir=out, render_structure=False,
            )
        self.assertEqual(len(payload['layout']['beds']), 100)
        self.assertEqual(payload['summary']['totalBeds'], 100)
        self.assertEqual(payload['summary']['totalQuantity'], 36)
        self.assertEqual(payload['summary']['unplacedBeds'], 0)
        self.assertTrue(payload['summary']['isEnough'])

    def test_partial_plan_reports_placed_beds(self):
        with tempfile.TemporaryDirectory() as out:
            payload = generate_plan_payload(
                100, 20, 30, 7, selected_modules={'A': 26, 'B': 4, 'C': 2, 'D': 4},
                output_dir=out, render_structure=False,
            )
        actual = len(payload['layout']['beds'])
        self.assertLess(actual, 100)
        self.assertEqual(payload['summary']['totalBeds'], actual)
        self.assertEqual(payload['selectionSummary']['totalBeds'], 100)
        self.assertEqual(payload['summary']['unplacedBeds'], 100 - actual)
        self.assertFalse(payload['summary']['isEnough'])
        public = to_v1_contract(payload, get_module_catalog(), {})
        self.assertEqual(public['layout']['totalBeds'], actual)
        self.assertEqual(public['summary']['totalBeds'], actual)
        self.assertIn(str(actual), public['textSummary'])
        self.assertEqual(public['recommendation']['summary']['totalBeds'], 100)

    def test_display_draws_one_texture_per_placed_module(self):
        result = calculate_layout(dict.fromkeys('ABCDEFG', 4), get_site_polygon(length_m=80, width_m=80))
        self.assertTrue(result.success)
        saved = []
        with patch('matplotlib.figure.Figure.savefig', lambda fig, *a, **k: saved.append(fig)):
            renderer.render_layout(result, 'unused.png', show_structure=False)
        images = saved[0].axes[0].images
        modules = [m for g in result.groups for m in g.modules]
        self.assertEqual(len(images), len(modules))
        for image, module in zip(images, modules):
            np.testing.assert_allclose(image.get_extent(), [module.x, module.x + module.occ_length_m,
                                                           module.y, module.y + module.occ_width_m])

    def test_texture_rotation_matches_clockwise_geometry(self):
        handler = renderer.TextureHandler()
        source = np.arange(18).reshape(2, 3, 3) / 18
        fig, ax = plt.subplots()
        try:
            handler.apply_texture(ax, 0, 0, 2, 3, source, rotated=True, mirror='horizontal')
            np.testing.assert_array_equal(ax.images[0].get_array(), np.rot90(np.fliplr(source), k=-1))
        finally:
            plt.close(fig)

    def test_missing_textures_still_draw_every_bed(self):
        result = calculate_layout({'B': 4}, get_site_polygon(length_m=12, width_m=8))
        handler = renderer.TextureHandler()
        handler.images = {}
        saved = []
        with patch.object(renderer, 'get_texture_handler', return_value=handler), \
                patch('matplotlib.figure.Figure.savefig', lambda fig, *a, **k: saved.append(fig)):
            renderer.render_layout(result, 'unused.png', show_structure=False)
        self.assertEqual(len(saved[0].axes[0].images), 0)
        self.assertEqual(len(saved[0].axes[0].patches), 1 + len(result.beds))

    def test_concurrent_render_outputs_are_deterministic(self):
        result = calculate_layout({'B': 4}, get_site_polygon(length_m=12, width_m=8))
        with tempfile.TemporaryDirectory() as out:
            def render(index):
                path = Path(out) / f'{index}.png'
                renderer.render_layout(result, path, show_structure=False)
                return hashlib.sha256(path.read_bytes()).hexdigest()
            with ThreadPoolExecutor(max_workers=3) as pool:
                hashes = list(pool.map(render, range(3)))
        self.assertEqual(len(set(hashes)), 1)


if __name__ == '__main__':
    unittest.main()
