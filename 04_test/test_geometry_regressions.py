"""Regressions for boundary containment, decomposing and rotated footprints."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '05_config_and_tools')]
import service_adapter  # sets up the project's import paths
from config_loader import get_group_defs, load_module_config
from geometry import point_in_polygon, rect_in_polygon, transform_module_polygon, transform_direction
from layout_optimizer import calculate_layout, _build_group_contents
from position_finder import calculate_group_size, find_best_position
from group_organizer import estimate_group_footprint

U_SITE = [(0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10)]


class GeometryRegressions(unittest.TestCase):
    def test_exact_fit_all_module_types(self):
        for code in 'ABCDEFG':
            with self.subTest(code=code):
                config = load_module_config(code)
                group = min(get_group_defs(code), key=lambda g: g['module_count'])
                w, h = calculate_group_size(group, config, False)
                result = calculate_layout({code: group['module_count']}, [(0, 0), (w, 0), (w, h), (0, h)])
                self.assertEqual(len(result.beds), group['module_count'] * len(config['beds_layout']))
                self.assertFalse(result.unplaced)

    def test_concave_boundary_cannot_cross_rectangle_interior(self):
        for polygon in [U_SITE, list(reversed(U_SITE)), U_SITE + [U_SITE[0]]]:
            self.assertFalse(rect_in_polygon((0, 0, 8, 4), polygon))
            self.assertTrue(rect_in_polygon((0, 0, 10, 3), polygon))
            self.assertTrue(rect_in_polygon((7, 3, 3, 7), polygon))
        diamond = [(0, 2), (2, 0), (4, 2), (2, 4)]
        self.assertTrue(point_in_polygon((3, 3), diamond))
        self.assertTrue(rect_in_polygon((1, 1, 2, 2), diamond))
        self.assertFalse(rect_in_polygon((0, 0, 4, 4), diamond))

    def test_concave_layout_decomposes_and_uses_legal_lobes(self):
        # Translation also ensures the search does not assume that (0, 0) is available.
        for dx, dy in [(0, 0), (20, 30), (-20, -30)]:
            site = [(x + dx, y + dy) for x, y in U_SITE]
            result = calculate_layout({'B': 4}, site)
            self.assertEqual(len(result.beds), 8)
            self.assertFalse(result.unplaced)
            self.assertEqual([g.module_count for g in result.groups], [2, 2])
            for g in result.groups:
                x, y, w, h = g.rect
                # Independent test: every group lies in one of the three legal rectangles.
                self.assertTrue((y + h <= dy + 3 + 1e-9) or
                                (x + w <= dx + 3 + 1e-9) or (x >= dx + 7 - 1e-9))

    def test_all_configured_beds_stay_inside_module(self):
        for code in 'ABCDEFG':
            config = load_module_config(code)
            for bed in config['beds_layout']:
                for x, y in bed['polygon']:
                    with self.subTest(code=code, bed=bed['bed_id'], point=(x, y)):
                        self.assertGreaterEqual(x, 0)
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x, config['dimensions']['length_mm'])
                        self.assertLessEqual(y, config['dimensions']['width_mm'])

    def test_sloping_site_can_find_a_boundary_contact_position(self):
        group = {'rows': 1, 'cols': 1, 'arrangement': [{'row': 0, 'col': 0}]}
        config = {'dimensions': {'length_mm': 2000, 'width_mm': 2000}}
        self.assertEqual(find_best_position(group, config, [], [(0, 2), (2, 0), (4, 2), (2, 4)]),
                         (1, 1, False, 2, 2))

    def test_mixed_rotations_use_one_consistent_grid(self):
        config = load_module_config('B')
        group = copy.deepcopy(get_group_defs('B')[0])
        group['module_id'] = 'B'
        group['internal_spacing'] = {'horizontal_gap_m': .5, 'vertical_gap_m': 1}
        group['arrangement'] = [dict(row=r, col=c, rotation=angle) for r, c, angle in
                                [(0, 0, 90), (0, 1, 0), (1, 0, 270), (1, 1, 180)]]
        self.assertEqual(estimate_group_footprint(group, config), (6.5, 9))
        for rotated, expected_rects in [(False, [(0, 0, 2, 4), (2.5, 0, 4, 2),
                                                (0, 5, 2, 4), (2.5, 5, 4, 2)]),
                                        (True, [(0, 4.5, 4, 2), (0, 0, 2, 4),
                                                (5, 4.5, 4, 2), (5, 0, 2, 4)])]:
            modules, beds, roads = [], [], []
            _build_group_contents(group, config, 0, 0, rotated, modules, beds, roads)
            self.assertEqual([m.rect for m in modules], expected_rects)
            self.assertEqual(len(beds), 8)

    def test_unsupported_rotation_is_rejected(self):
        for angle in [45, 90.5, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                transform_module_polygon([(0, 0)], 4000, 2000, 'none', angle)

    def test_quarter_turns_match_footprint_beds_and_direction(self):
        config = load_module_config('B')
        for rotation in [0, 90, 180, 270]:
            for mirror in ['none', 'horizontal', 'vertical', 'both']:
                for group_rotated in [False, True]:
                    with self.subTest(rotation=rotation, mirror=mirror, group_rotated=group_rotated):
                        group = copy.deepcopy(get_group_defs('B')[-1])
                        group['module_id'] = 'B'
                        group['arrangement'][0].update(rotation=rotation, mirror=mirror)
                        expected = (2, 4) if (rotation + 90 * group_rotated) % 180 else (4, 2)
                        self.assertEqual(calculate_group_size(group, config, group_rotated), expected)
                        modules, beds, roads = [], [], []
                        _build_group_contents(group, config, 10, 20, group_rotated, modules, beds, roads)
                        self.assertEqual(modules[0].rect, (10, 20, *expected))
                        for bed in beds:
                            for x, y in bed.polygon_m:
                                self.assertTrue(10 <= x <= 10 + expected[0])
                                self.assertTrue(20 <= y <= 20 + expected[1])
        self.assertEqual(transform_direction('north', 'none', 270), 'west')
        self.assertEqual(transform_direction('north', 'none', 180), 'south')
        expected_points = {0: (500, 250), 90: (250, 3500), 180: (3500, 1750), 270: (1750, 500)}
        for angle, point in expected_points.items():
            self.assertEqual(transform_module_polygon([(500, 250)], 4000, 2000, 'none', angle)[0][0], point)


if __name__ == '__main__':
    unittest.main()
