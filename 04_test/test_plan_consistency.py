"""Regression tests for selected/placed counts and per-module rendering."""
import sys
import tempfile
import unittest
import hashlib
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '05_config_and_tools')]
from service_adapter import generate_plan_payload
from cloudrun_app.contract import to_v1_contract
from config_loader import get_module_catalog, get_site_polygon, load_module_config, get_group_defs
from layout_optimizer import calculate_layout, _build_group_contents
import renderer
import numpy as np
import matplotlib.pyplot as plt


class PlanConsistencyTests(unittest.TestCase):
    def test_downsampling_does_not_erase_thin_texture_lines(self):
        # A subpixel bed outline must remain visible in a small module image.
        source = np.ones((100, 100, 3))
        source[:, 2] = 0
        fig = plt.figure(figsize=(1, 1), dpi=30)
        ax = fig.add_axes((0, 0, 1, 1))
        try:
            ax.set_axis_off()
            renderer.TextureHandler().apply_texture(ax, 0, 0, 100, 100, source)
            ax.set_xlim(0, 100)
            ax.set_ylim(0, 100)
            fig.canvas.draw()
            pixels = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
            self.assertLess(pixels.min(), 245)
        finally:
            plt.close(fig)

    def test_g_bed_four_faces_its_south_pillow_after_transforms(self):
        config = load_module_config('G')
        for mirror, normal, rotated in [
            ('none', 'south', 'west'), ('horizontal', 'south', 'west'),
            ('vertical', 'north', 'east'), ('both', 'north', 'east'),
        ]:
            for is_rotated, expected in [(False, normal), (True, rotated)]:
                with self.subTest(mirror=mirror, rotated=is_rotated):
                    group = copy.deepcopy(get_group_defs('G')[0])
                    group['module_id'] = 'G'
                    group['arrangement'][0]['mirror'] = mirror
                    modules, beds, roads = [], [], []
                    _build_group_contents(group, config, 0, 0, is_rotated, modules, beds, roads)
                    self.assertEqual(len(beds), 4)
                    self.assertEqual(next(b for b in beds if b.bed_id == 4).head_direction, expected)

    def test_full_100_bed_plan_counts_match(self):
        with tempfile.TemporaryDirectory() as out:
            payload = generate_plan_payload(
                100, 30, 70, 7, selected_modules={'A': 26, 'B': 4, 'C': 2, 'D': 4},
                output_dir=out, render_structure=False,
            )
        self.assertEqual(len(payload['layout']['beds']), 100)
        self.assertEqual(payload['summary']['totalBeds'], 100)
        self.assertEqual(payload['summary']['totalQuantity'], 36)
        self.assertEqual(payload['summary']['unplacedBeds'], 0)
        self.assertTrue(payload['summary']['isEnough'])

    def test_partial_plan_is_rejected_before_rendering(self):
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaisesRegex(ValueError, '最大模块数量'):
                generate_plan_payload(
                    100, 20, 30, 7, selected_modules={'A': 26, 'B': 4, 'C': 2, 'D': 4},
                    output_dir=out, render_structure=False,
                )
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_display_draws_one_texture_per_placed_module(self):
        result = calculate_layout(dict.fromkeys('ABCDEFG', 4), get_site_polygon(length_m=80, width_m=80))
        # Rendering counts are independent of a layout's path acceptance.
        # Preserve every placed module even when an audit rejects the plan.
        self.assertEqual(sum(len(g.modules) for g in result.groups), 28)
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

    def test_render_uses_each_module_full_rotation(self):
        result = calculate_layout({'B': 1}, get_site_polygon(length_m=10, width_m=10))
        handler = renderer.TextureHandler()
        source = np.arange(18).reshape(2, 3, 3) / 18
        module = result.groups[0].modules[0]
        for angle in [0, 90, 180, 270]:
            for mirror in ['none', 'horizontal', 'vertical', 'both']:
                module.rotation, module.mirror = angle, mirror
                module.occ_length_m, module.occ_width_m = (2, 4) if angle % 180 else (4, 2)
                saved = []
                with patch.object(renderer, 'get_texture_handler', return_value=handler), \
                        patch.object(handler, 'get_module_texture', return_value=source), \
                        patch('matplotlib.figure.Figure.savefig', lambda fig, *a, **k: saved.append(fig)):
                    renderer.render_layout(result, 'unused.png', show_structure=False)
                expected = source
                if mirror in ('horizontal', 'both'):
                    expected = np.fliplr(expected)
                if mirror in ('vertical', 'both'):
                    expected = np.flipud(expected)
                image = saved[0].axes[0].images[0]
                np.testing.assert_array_equal(image.get_array(), np.rot90(expected, k=-angle // 90))
                self.assertEqual(tuple(image.get_extent()), (module.x, module.x + module.occ_length_m,
                                                             module.y, module.y + module.occ_width_m))

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
