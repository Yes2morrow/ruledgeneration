"""Actual openings, public clearance and independently checked geometry."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '05_config_and_tools'))
import service_adapter
from config_loader import get_group_defs, load_module_config
from geometry import PlacedModule
from layout_optimizer import calculate_layout, layout_result_to_dict
from road_connectivity import RoadNetwork

SITE = [(0,0),(20,0),(20,30),(0,30)]
U_SITE = [(0,0),(10,0),(10,10),(7,10),(7,3),(3,3),(3,10),(0,10)]


def module(x=5, y=5, aisle=(0,1,4,3)):
    cfg = dict(road_areas=[], beds_layout=[])
    if aisle:
        ax,ay,bx,by=aisle
        cfg['road_areas']=[dict(polygon=[(ax*1000,ay*1000),(bx*1000,ay*1000),
                                       (bx*1000,by*1000),(ax*1000,by*1000)])]
        cfg['beds_layout']=[dict(polygon=[(0,0),(4000,0),(4000,ay*1000),(0,ay*1000)]),
                            dict(polygon=[(0,by*1000),(4000,by*1000),(4000,4000),(0,4000)])]
    else:
        cfg['beds_layout']=[dict(polygon=[(0,0),(4000,0),(4000,4000),(0,4000)])]
    return PlacedModule('test','test',x,y,0,'none',4000,4000,4,4,cfg)


class RoadConnectivityTests(unittest.TestCase):
    def test_fast_opening_rejection_agrees_with_full_geometry(self):
        import random
        rng = random.Random(1903060)
        for rotation in (0, 90, 180, 270):
            base = [module(5, 5), module(12, 14)]
            network = RoadNetwork(SITE, base)
            for _ in range(60):
                candidate = replace(module(round(rng.uniform(.1, 16), 3),
                                           round(rng.uniform(.1, 26), 3)), rotation=rotation)
                # Only disjoint footprints are candidates at the packing seam.
                shape = network._geometry(candidate)[0]
                if any(shape.intersection(item[0]).area > 1e-6 for item in network.items):
                    continue
                self.assertEqual(network.evaluate([candidate], include_roads=False).valid,
                                 RoadNetwork(SITE, base + [candidate]).evaluate().valid)

    def test_translated_geometry_cache_matches_the_scalar_rounding_path(self):
        network = RoadNetwork(SITE)
        for rotation in (0, 90, 180, 270):
            for mirror in ('none', 'horizontal', 'vertical', 'both'):
                original = replace(module(5.2, 5.3), rotation=rotation, mirror=mirror)
                # Off-grid epsilon selects the scalar branch, but rounds to the
                # identical millimetre coordinates used by the translation cache.
                scalar = network._geometry(replace(original, x=original.x + .0000001))
                cached = network._geometry(original)
                self.assertTrue(cached[0].equals(scalar[0]))
                for index in (1, 2, 4):
                    self.assertEqual(len(cached[index]), len(scalar[index]))
                    self.assertTrue(all(a.equals(b) for a, b in zip(cached[index], scalar[index])))
                self.assertEqual(cached[5], scalar[5])

    def test_all_group_external_gaps_stay_zero(self):
        for code in 'ABCDEFG':
            for group in get_group_defs(code):
                self.assertEqual(group['external_spacing'], {'horizontal_gap_m':0,'vertical_gap_m':0})

    def test_wall_cannot_be_rescued_by_a_detour_through_another_opening(self):
        result = RoadNetwork(SITE,[module(),module(9,5,(0,3.3,4,3.8))]).evaluate()
        self.assertFalse(result.valid)
        self.assertTrue(any('墙面' in e['reason'] for e in result.opening_errors))

    def test_matching_openings_create_a_direct_connection(self):
        result = RoadNetwork(SITE,[module(),module(9,5)]).evaluate()
        self.assertTrue(result.valid)

    def test_a_wide_exit_cannot_rescue_another_opening_to_a_narrow_gap(self):
        result = RoadNetwork(SITE,[module(.8,5)]).evaluate()
        self.assertFalse(result.valid)

    def test_internal_aisle_may_be_narrower_than_public_road(self):
        self.assertTrue(RoadNetwork(SITE,[module(5,5,(0,1,4,1.5))]).evaluate().valid)

    def test_site_edge_is_not_an_implicit_exit(self):
        self.assertFalse(RoadNetwork(SITE,[module(0,5)]).evaluate().valid)

    def test_missing_aisles_never_silently_pass(self):
        result = RoadNetwork(SITE,[module(aisle=None)]).evaluate()
        self.assertEqual(result.blocked_indices,[0])
        self.assertFalse(result.valid)

    def test_adding_a_module_rechecks_existing_openings(self):
        network = RoadNetwork(SITE,[module()])
        self.assertTrue(network.evaluate().valid)
        self.assertFalse(network.evaluate([module(9,5,(0,3.3,4,3.8))],include_roads=False).valid)

    def test_cache_does_not_change_decisions_or_hide_final_failures(self):
        a,b=module(),module(9,5)
        network=RoadNetwork(SITE,[a])
        trial=[b]
        self.assertTrue(network.evaluate(trial,include_roads=False).valid)
        network.commit(trial)
        self.assertTrue(network._ports)
        fresh=RoadNetwork(SITE,[a,b]).evaluate()
        cached=network.evaluate()
        self.assertEqual(cached.blocked_indices,fresh.blocked_indices)
        self.assertCountEqual(cached.opening_errors,fresh.opening_errors)
        self.assertAlmostEqual(cached.reachable_area,fresh.reachable_area)

    def test_cached_opening_is_invalidated_when_a_new_module_blocks_it(self):
        a,b=module(),module(9,5)
        network=RoadNetwork(SITE,[a])
        trial=[b]
        self.assertTrue(network.evaluate(trial,include_roads=False).valid)
        network.commit(trial)
        # The new module has valid openings of its own, but blocks B's right mouth.
        blocker=module(13.5,4,(0,3.3,4,3.8))
        cached=network.evaluate([blocker])
        fresh=RoadNetwork(SITE,[a,b,blocker]).evaluate()
        self.assertFalse(cached.valid)
        self.assertEqual(cached.blocked_indices,fresh.blocked_indices)
        self.assertCountEqual(cached.opening_errors,fresh.opening_errors)
        self.assertAlmostEqual(cached.reachable_area,fresh.reachable_area)

    def test_g_separates_both_sides_of_its_impenetrable_cabinet(self):
        cfg=load_module_config('G')
        roads=[Polygon(r['polygon']) for r in cfg['road_areas']]
        self.assertEqual(len(roads),2)
        self.assertFalse(roads[0].intersects(roads[1]))
        self.assertFalse(unary_union(roads).intersects(box(1000,1900,1800,2200)))

    def test_every_configured_bed_touches_a_real_aisle_without_overlap(self):
        for code in 'ABCDEFG':
            cfg=load_module_config(code)
            roads=unary_union([Polygon(r['polygon']) for r in cfg['road_areas']])
            bounds=box(0,0,cfg['dimensions']['length_mm'],cfg['dimensions']['width_mm'])
            self.assertTrue(roads.is_valid,code)
            self.assertTrue(bounds.covers(roads),code)
            for bed in cfg['beds_layout']:
                shape=Polygon(bed['polygon'])
                self.assertLess(shape.intersection(roads).area,1e-5,code)
                self.assertGreater(shape.boundary.intersection(roads).length,0,code)

    def test_dense_64_bed_case_cannot_pass_after_path_repair_loses_modules(self):
        result=calculate_layout({'D':2,'G':12,'C':4},SITE)
        self.assertFalse(result.success)
        self.assertTrue(result.unplaced or not result.metrics['route_access_valid'])
        self.assertEqual(result.metrics['public_road_width_m'],1.2)
        self.assertFalse(result.metrics['road_width_reduced'])
        self.assertEqual(result.metrics['road_opening_errors_count'],0)

    def test_u_site_does_not_shrink_roads_to_force_the_selection(self):
        result=calculate_layout({'B':4},U_SITE)
        self.assertFalse(result.success)
        self.assertEqual(result.metrics['public_road_width_m'],1.2)
        self.assertFalse(result.metrics['road_width_reduced'])
        with self.assertRaises(ValueError):
            calculate_layout({'B':4},U_SITE,public_road_width_m=1.0)

    def test_disabling_candidate_filter_does_not_fake_a_pass(self):
        result=calculate_layout({'D':2,'G':12,'C':4},SITE,road_check=False)
        self.assertTrue(result.metrics['road_connectivity_checked'])
        self.assertFalse(result.metrics['road_candidate_filter_enabled'])
        self.assertFalse(result.metrics['road_connected'])
        self.assertFalse(result.success)

    def test_serialized_roads_exclude_beds_and_module_barriers(self):
        result=calculate_layout({'G':1},SITE)
        payload=layout_result_to_dict(result)
        roads=unary_union([Polygon(r['polygon_m'],r['holes_m']) for r in payload['roads']
                          if r['source'] in ['module','walkable']])
        for b in result.beds:
            self.assertLess(roads.intersection(Polygon(b.polygon_m)).area,1e-8)
        m=result.groups[0].modules[0]
        self.assertLess(roads.intersection(box(m.x+1,m.y+1.9,m.x+1.8,m.y+2.2)).area,1e-8)

    def test_public_width_cannot_drop_below_user_minimum(self):
        for width in [.9, float('nan'), float('inf')]:
            with self.subTest(width=width), self.assertRaises(ValueError):
                RoadNetwork(SITE,public_width_m=width)


if __name__=='__main__':
    unittest.main()
