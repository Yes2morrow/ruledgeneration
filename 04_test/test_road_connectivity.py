"""Zero-gap layouts must preserve an actual route for every placed bed."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '05_config_and_tools'))
import service_adapter
from config_loader import get_group_defs
from geometry import BedInstance, rects_violate_spacing
from layout_optimizer import calculate_layout, layout_result_to_dict
from road_connectivity import RoadNetwork
from shapely.geometry import Polygon
from shapely.ops import unary_union


def bed(x, y, w, h):
    return BedInstance(1, 'test', 'test', [(x,y),(x+w,y),(x+w,y+h),(x,y+h)], 'north', 0)


def independent_blocked(result):
    # Independent full rebuild: no candidate cache or production checker.
    site = Polygon(result.site_polygon)
    polygons = [Polygon([(round(x,3),round(y,3)) for x,y in b.polygon_m]) for b in result.beds]
    free = site.difference(unary_union(polygons))
    parts = [free] if free.geom_type == 'Polygon' else list(free.geoms)
    reachable = unary_union([p for p in parts if p.boundary.intersection(site.boundary).length > 1e-7])
    return [i for i,p in enumerate(polygons)
            if p.boundary.intersection(reachable.boundary.buffer(1e-8)).length < 1e-6]


class RoadConnectivityTests(unittest.TestCase):
    def test_all_group_external_gaps_are_zero_and_overlap_is_still_rejected(self):
        for code in 'ABCDEFG':
            for group in get_group_defs(code):
                self.assertEqual(group['external_spacing'], {'horizontal_gap_m':0,'vertical_gap_m':0})
        self.assertFalse(rects_violate_spacing((0,0,4,2),(4,0,4,2),0))
        self.assertTrue(rects_violate_spacing((0,0,4,2),(3.999,0,4,2),0))

    def test_closing_a_route_must_recheck_existing_beds(self):
        site = [(0,0),(10,0),(10,10),(0,10)]
        # Open ring and an interior bed. The closing bed itself has an exit,
        # but adding it traps the already placed interior bed.
        existing = [bed(2,2,6,1), bed(2,7,6,1), bed(2,3,1,4), bed(4,4,2,2)]
        network = RoadNetwork(site, existing)
        self.assertEqual(network.evaluate().blocked_indices, [])
        checked = network.evaluate([bed(7,3,1,4)])
        self.assertEqual(checked.blocked_indices, [3])
        self.assertGreater(checked.isolated_area, 0)

    def test_bed_touching_site_boundary_does_not_replace_an_actual_road(self):
        checked = RoadNetwork([(0,0),(4,0),(4,2),(0,2)], [bed(0,0,4,2)]).evaluate()
        self.assertEqual(checked.blocked_indices, [0])

    def test_empty_site_has_no_blocked_beds_and_bounded_road_area(self):
        checked = RoadNetwork([(0,0),(10,0),(10,10),(0,10)], []).evaluate()
        self.assertEqual(checked.blocked_indices, [])
        self.assertEqual(checked.reachable_area, 100)

    def test_corner_only_opening_does_not_connect_an_enclosed_bed(self):
        walls = [bed(2,2,5,1),bed(7,3,1,5),bed(3,7,4,1),bed(2,3,1,4)]
        checked = RoadNetwork([(0,0),(10,0),(10,10),(0,10)],walls+[bed(4,4,1,1)]).evaluate()
        self.assertIn(4,checked.blocked_indices)

    def test_road_holes_exclude_beds_and_survive_api_serialization(self):
        from geometry import LayoutResult
        checked = RoadNetwork([(0,0),(10,0),(10,10),(0,10)],[bed(4,4,2,2)]).evaluate()
        data = layout_result_to_dict(LayoutResult(site_polygon=[],roads=checked.roads))
        roads = [Polygon(r['polygon_m'],r['holes_m']) for r in data['roads']]
        self.assertEqual(sum(r.area for r in roads),96)
        self.assertEqual(len(data['roads'][0]['holes_m']),1)
        self.assertEqual(unary_union(roads).intersection(Polygon(bed(4,4,2,2).polygon_m)).area,0)

    def test_real_zero_gap_counterexample_is_rearranged_without_losing_beds(self):
        site = [(0,0),(20,0),(20,30),(0,30)]
        result = calculate_layout({'D':2,'G':12,'C':4}, site)
        self.assertEqual(len(result.beds), 64)
        self.assertTrue(result.success)
        self.assertEqual(independent_blocked(result), [])
        self.assertTrue(result.metrics['road_connectivity_checked'])
        self.assertEqual(result.metrics['beds_without_road_access_count'], 0)
        self.assertLessEqual(result.metrics['road_area_m2'], 600)
        serialized = layout_result_to_dict(result)
        self.assertTrue(all(r['source'] != 'module_perimeter' for r in serialized['roads']))

    def test_u_site_uses_two_touching_groups_with_roads_connected(self):
        site = [(0,0),(10,0),(10,10),(7,10),(7,3),(3,3),(3,10),(0,10)]
        result = calculate_layout({'B':4}, site)
        self.assertEqual([g.module_count for g in result.groups], [2,2])
        self.assertEqual(len(result.beds), 8)
        self.assertEqual(independent_blocked(result), [])

    def test_disabling_candidate_check_does_not_claim_connectivity_passed(self):
        result = calculate_layout({'D':2,'G':12,'C':4}, [(0,0),(20,0),(20,30),(0,30)], road_check=False)
        self.assertTrue(independent_blocked(result))
        self.assertTrue(result.metrics['road_connectivity_checked'])
        self.assertFalse(result.metrics['road_candidate_filter_enabled'])
        self.assertFalse(result.metrics['road_connected'])
        self.assertFalse(result.success)


if __name__ == '__main__':
    unittest.main()
