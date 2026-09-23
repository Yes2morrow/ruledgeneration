"""A remainder module must follow its module row rather than float at a corner."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '05_config_and_tools'))
import service_adapter
from position_finder import _score
from config_loader import get_site_polygon
from capacity_service import checked_layout


class SupplementPlacementTests(unittest.TestCase):
    def test_190_on_30_by_60_keeps_remainder_pairs_in_one_column(self):
        layout = checked_layout({'E': 61, 'B': 2, 'F': 1},
                                get_site_polygon(length_m=30, width_m=60))
        self.assertTrue(layout.success)
        self.assertEqual(len(layout.beds), 190)
        pairs = [g for g in layout.groups if g.module_id == 'E' and g.module_count == 2]
        self.assertGreaterEqual(len(pairs), 4)
        self.assertLess(max(g.x for g in pairs) - min(g.x for g in pairs), .001,
                        'Remainder pairs must not step sideways into the neighbouring column')
        self.assertTrue(layout.metrics['road_connected'])
        self.assertTrue(layout.metrics['route_access_valid'])

    def test_single_b_prefers_the_orientation_of_its_existing_column(self):
        group = {'module_id': 'B', 'external_spacing': {}, '_align_supplement': True}
        placed = [SimpleNamespace(module_id='B', rotated=True, rect=(1.3, 27.2, 2, 8), _group_def=group),
                  SimpleNamespace(module_id='B', rotated=True, rect=(1.3, 35.2, 2, 8), _group_def=group)]
        adjacent = (1.3, 43.2, True, 2, 4)
        corner = (.5, 68, False, 4, 2)
        self.assertLess(_score(adjacent, placed, [], group), _score(corner, placed, [], group))

    def test_real_190_bed_mix_keeps_its_supplement_in_the_same_column(self):
        layout = checked_layout({'A': 60, 'B': 5}, get_site_polygon(length_m=30, width_m=70))
        self.assertTrue(layout.success)
        self.assertEqual(len(layout.beds), 190)
        supplements = [g for g in layout.groups if g.module_id == 'B']
        single = next(g for g in supplements if g.module_count == 1)
        pairs = [g for g in supplements if g.module_count == 2]
        self.assertTrue(single.rotated)
        self.assertTrue(all(abs(single.x - pair.x) < .001 for pair in pairs))
        # Leave an access break when touching the column would create a detour.
        self.assertLessEqual(min(min(abs(single.y - (p.y + p.width_m)),
                                     abs(single.y + single.width_m - p.y)) for p in pairs), 4.01)
        self.assertTrue(layout.metrics['route_access_valid'])


if __name__ == '__main__':
    unittest.main()
