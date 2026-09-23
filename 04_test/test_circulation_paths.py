"""Real shortest paths must see walls, narrow slots and useful cross aisles."""
import sys
import unittest
import math
from pathlib import Path
import shapely
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '02_placement_generation')]
from circulation_paths import route_distances, repair_corridor


class CirculationPathTests(unittest.TestCase):
    def test_millimetre_geometry_retains_a_valid_internal_aisle(self):
        domain = shapely.set_precision(box(26.3, 5.35, 27.7, 6.65), .001)
        points = [(26.3, 6), (27.7, 6)]
        distances = route_distances(domain, points)
        self.assertAlmostEqual(distances[0, 1], 1.4)
        self.assertAlmostEqual(distances[1, 0], 1.4)

    def test_numerical_tolerance_does_not_cross_a_millimetre_wall(self):
        domain = shapely.set_precision(
            box(0, 0, 10, 4).difference(box(5, 0, 5.001, 4)), .001)
        distance = route_distances(domain, [(4, 2), (6, 2)])[0, 1]
        self.assertTrue(math.isinf(distance))

    def test_nearby_points_across_a_long_wall_require_a_real_detour(self):
        site = box(0, 0, 30, 50)
        wall = box(14, 2, 16, 48)
        points = [(13, 25), (17, 25)]
        path = route_distances(site.difference(wall), points)[0, 1]
        self.assertAlmostEqual(path, 50)
        self.assertGreater(path - 4, 20)
        crossing = box(0, 24.4, 30, 25.6)
        repaired = site.difference(wall.difference(crossing))
        self.assertAlmostEqual(route_distances(repaired, points)[0, 1], 4)

    def test_disconnected_regions_are_not_joined_by_straight_line_distance(self):
        domain = box(0, 0, 4, 4).union(box(6, 0, 10, 4))
        self.assertTrue(math.isinf(route_distances(domain, [(3, 2), (7, 2)])[0, 1]))

    def test_l_shaped_route_does_not_cut_the_corner(self):
        domain = box(0, 0, 10, 2).union(box(8, 0, 10, 10))
        self.assertAlmostEqual(route_distances(domain, [(1, 1), (9, 9)])[0, 1], 16)

    def test_repair_follows_failure_location_and_works_on_both_axes(self):
        site = [(0, 0), (30, 0), (30, 50), (0, 50)]
        failure = {'from': (13, 25), 'to': (17, 25), 'path_m': 50, 'direct_m': 4}
        horizontal = repair_corridor(site, [failure], [])
        self.assertEqual(horizontal, (0, 24.4, 30, 1.2))
        failure.update({'from': (12, 20), 'to': (12, 24)})
        self.assertEqual(repair_corridor(site, [failure], []), (11.4, 0, 1.2, 50))
        self.assertIsNone(repair_corridor(site, [], []))


if __name__ == '__main__':
    unittest.main()
