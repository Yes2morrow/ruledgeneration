"""Final tidying must retain a feasible cart and align across module types."""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '05_config_and_tools'))
import service_adapter
import capacity_service
from capacity_service import checked_layout
from config_loader import get_site_polygon, get_group_defs, load_module_config
from layout_optimizer import _build_group_contents, _compute_metrics
from position_finder import calculate_group_size
from geometry import PlacedGroup, LayoutResult
from road_connectivity import RoadNetwork
from circulation_paths import audit_bed_routes
from layout_alignment import tidy_layout


def fixture(code, other='B', rotated=False):
    groups, beds = [], []
    for module_id, x, y in [(code, 5, 5), (other, 25, 5.35)]:
        config = load_module_config(module_id)
        definition = dict(get_group_defs(module_id)[-1], module_id=module_id)
        w, h = calculate_group_size(definition, config, rotated)
        group = PlacedGroup(definition['group_type'], module_id, x, y, rotated, w, h,
                            definition['rows'], definition['cols'], definition['module_count'],
                            definition.get('external_spacing', {}))
        group._group_def = definition
        _build_group_contents(definition, config, x, y, rotated, group.modules, beds, [])
        groups.append(group)
    site = get_site_polygon(length_m=50, width_m=30)
    network = RoadNetwork(site, [m for g in groups for m in g.modules])
    road = network.evaluate()
    paths = audit_bed_routes(network)
    assert road.valid, road.opening_errors
    assert paths['route_access_valid'], paths
    return LayoutResult(site_polygon=site, groups=groups, beds=beds, roads=road.roads,
                        metrics={**_compute_metrics(groups, beds, site, road.roads), **paths,
                                 'public_road_width_m': 1.2, 'road_connected': True}, success=True)


class FinalAlignmentTests(unittest.TestCase):
    def test_every_module_type_can_align_with_another_type(self):
        for code in 'ABCDEFG':
            for rotated in (False, True):
                with self.subTest(code=code, rotated=rotated):
                    original = fixture(code, 'E' if code == 'B' else 'B', rotated)
                    original_positions = [(g.x, g.y) for g in original.groups]
                    result = tidy_layout(original)
                    a, b = result.groups
                    # Real modules inside a group can provide row baselines,
                    # including when their outer group rectangles differ.
                    bottom_a = {round(m.y, 3) for m in a.modules}
                    bottom_b = {round(m.y, 3) for m in b.modules}
                    top_a = {round(m.y + m.occ_width_m, 3) for m in a.modules}
                    top_b = {round(m.y + m.occ_width_m, 3) for m in b.modules}
                    self.assertTrue(bottom_a & bottom_b or top_a & top_b)
                    self.assertNotEqual([(g.x, g.y) for g in result.groups], original_positions)
                    self.assertEqual(len(result.beds), len(original.beds))
                    self.assertTrue(result.metrics['route_access_valid'])
                    self.assertEqual([(g.x, g.y) for g in original.groups], original_positions)

    def test_failed_route_audit_and_exhausted_budget_keep_original(self):
        original = fixture('E')
        with patch('layout_alignment.audit_bed_routes', return_value={'route_access_valid': False}):
            self.assertIs(tidy_layout(original), original)
        with patch('layout_alignment.check_budget', side_effect=TimeoutError('budget')):
            self.assertIs(tidy_layout(original), original)
        with patch('layout_alignment.audit_bed_routes', side_effect=ValueError('graph too large')):
            with self.assertLogs('layout_alignment', level='ERROR') as messages:
                self.assertIs(tidy_layout(original), original)
            self.assertIn('graph too large', '\n'.join(messages.output))

    def test_timed_out_finalization_can_retry_using_the_verified_layout(self):
        original = fixture('E')
        before = [(g.x, g.y) for g in original.groups]
        selection = {group.module_id: group.module_count for group in original.groups}
        capacity_service._layout.cache_clear()
        capacity_service._final_layout.cache_clear()
        try:
            with patch('capacity_service.calculate_layout', return_value=original) as calculate:
                with patch('layout_alignment.check_budget', side_effect=TimeoutError('budget')):
                    fallback = checked_layout(selection, original.site_polygon, finalize=True)
                self.assertEqual([(g.x, g.y) for g in fallback.groups], before)
                self.assertTrue(fallback.metrics['route_access_valid'])
                retried = checked_layout(selection, original.site_polygon, finalize=True)
                self.assertNotEqual([(g.x, g.y) for g in retried.groups], before)
                self.assertTrue(retried.metrics['route_access_valid'])
                self.assertEqual([(g.x, g.y) for g in original.groups], before)
                calculate.assert_called_once()
        finally:
            capacity_service._layout.cache_clear()
            capacity_service._final_layout.cache_clear()

    def test_final_cache_is_separate_and_does_not_mutate_capacity_result(self):
        site = get_site_polygon(length_m=30, width_m=60)
        selected = {'E': 61, 'B': 2, 'F': 1}
        raw = checked_layout(selected, site)
        before = [(g.x, g.y) for g in raw.groups]
        finished = checked_layout(selected, site, finalize=True)
        self.assertNotEqual(before, [(g.x, g.y) for g in finished.groups])
        finished.groups[0].x = -999
        self.assertEqual(before, [(g.x, g.y) for g in checked_layout(selected, site).groups])
        self.assertGreaterEqual(checked_layout(selected, site, finalize=True).groups[0].x, 0)

    def test_190_rows_and_different_remainders_share_existing_edges(self):
        result = checked_layout({'E': 61, 'B': 2, 'F': 1},
                                get_site_polygon(length_m=30, width_m=60), finalize=True)
        self.assertTrue(result.success)
        self.assertEqual(len(result.beds), 190)
        self.assertTrue(result.metrics['road_connected'])
        self.assertTrue(result.metrics['route_access_valid'])
        self.assertEqual(result.metrics['public_road_width_m'], 1.2)
        big = next(g for g in result.groups if g.module_id == 'E' and g.module_count == 16)
        rows = {round(m.y, 3) for m in big.modules}
        pairs = [g for g in result.groups if g.module_id == 'E' and g.module_count == 2]
        self.assertTrue(all(round(g.y, 3) in rows for g in pairs),
                        'Remainders should inherit available row baselines, not accumulate 0.3m offsets')
        e = next(g for g in result.groups if g.module_id == 'E' and g.module_count == 1)
        f = next(g for g in result.groups if g.module_id == 'F')
        self.assertTrue(abs(e.y-f.y) < .001 or
                        abs(e.y+e.width_m-f.y-f.width_m) < .001,
                        'Different module types may share a top or bottom edge')


if __name__ == '__main__':
    unittest.main()
