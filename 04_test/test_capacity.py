"""Real geometry regressions for site, cart and target-bed matching."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '05_config_and_tools')]
from service_adapter import generate_recommendation_payload, generate_plan_payload, normalize_selected_modules
from capacity_service import preflight, check_cart, checked_layout
from config_loader import get_site_polygon


class CapacityTests(unittest.TestCase):
    def test_190_is_exact_and_preview_never_renders_or_tidies(self):
        with patch('service_adapter.render_layout') as render, \
                patch('capacity_service._final_layout') as finish:
            payload = generate_recommendation_payload(190, 30, 70, 2, strategy_key='comfort', preview_only=True)
        self.assertEqual(sum(item['module_count'] for item in payload['layout']['groups']),
                         payload['summary']['totalQuantity'])
        self.assertEqual(payload['summary']['totalBeds'], 190)
        self.assertTrue(payload['layout']['success'])
        self.assertEqual(payload['layout']['outputFiles'], {})
        self.assertTrue(payload['layout']['metrics']['route_access_valid'])
        self.assertGreater(payload['layout']['metrics']['route_pairs_checked'], 0)
        render.assert_not_called()
        finish.assert_not_called()

    def test_main_corridors_stay_empty_and_span_the_site(self):
        from shapely.geometry import box, Polygon
        site = get_site_polygon(length_m=30, width_m=70)
        result = checked_layout({'A': 60, 'B': 5}, site)
        self.assertTrue(result.success)
        corridors = result.metrics['main_corridors']
        self.assertGreater(len(corridors), 0)
        for corridor_data in corridors:
            x, y, width, height = (corridor_data[k] for k in ('x', 'y', 'width', 'height'))
            self.assertAlmostEqual(min(width, height), 1.2)
            corridor = box(x, y, x+width, y+height)
            for group in result.groups:
                gx, gy, gw, gh = group.rect
                self.assertLess(corridor.intersection(box(gx, gy, gx+gw, gy+gh)).area, 1e-8)
        self.assertTrue(result.metrics['road_connected'])

    def test_natural_aisles_need_no_fixed_partition(self):
        result = checked_layout({'E': 60}, get_site_polygon(length_m=30, width_m=60))
        self.assertTrue(result.success)
        self.assertTrue(result.metrics['route_access_valid'])
        self.assertEqual(result.metrics['main_corridor_count'], 0)

    def test_180_30_by_60_is_not_falsely_rejected(self):
        self.assertTrue(preflight(180, 30, 60, 2)['isValid'])
        payload = generate_recommendation_payload(180, 30, 60, 2, strategy_key='comfort', preview_only=True)
        self.assertEqual(payload['summary']['totalBeds'], 180)

    def test_overflow_returns_a_reproducible_capacity(self):
        result = preflight(22, 8, 8, 2)
        self.assertFalse(result['isValid'])
        self.assertIn(str(result['maxEvacuees']), result['message'])
        layout = checked_layout(result['capacitySelection'], get_site_polygon(length_m=8, width_m=8))
        self.assertTrue(layout.success)
        self.assertEqual(len(layout.beds), result['maxEvacuees'])
        self.assertTrue(preflight(result['maxEvacuees'], 8, 8, 2)['isValid'])

    def test_cart_overflow_returns_verified_limit_for_the_actual_mix(self):
        result = check_cart(12, 8, {'B': 30}, 'B')
        self.assertFalse(result['isValid'])
        self.assertIn('最大模块数量', result['message'])
        self.assertEqual(result['maxModules'], sum(result['fittingSelection'].values()))
        self.assertTrue(check_cart(12, 8, result['fittingSelection'])['isValid'])

    def test_invalid_steps_dimensions_and_quantities(self):
        with self.assertRaisesRegex(ValueError, '倍数'):
            preflight(2, 12, 8, 2, selected_modules={'A': 3})
        for selected in ({'A': -2}, {'B': 1.5}, {'X': 1}):
            with self.assertRaises(ValueError):
                normalize_selected_modules(selected)
        with self.assertRaises(ValueError):
            preflight(2, -12, -8, 2)

    def test_cart_and_recommendation_use_identical_order(self):
        site = get_site_polygon(length_m=30, width_m=45)
        first = checked_layout({'E': 8, 'B': 4, 'A': 4}, site)
        second = checked_layout({'A': 4, 'B': 4, 'E': 8}, site)
        self.assertEqual(first.success, second.success)
        self.assertEqual([(g.x, g.y, g.module_id) for g in first.groups],
                         [(g.x, g.y, g.module_id) for g in second.groups])

    def test_generation_rechecks_capacity_and_produces_no_partial_image(self):
        with tempfile.TemporaryDirectory() as out, patch('service_adapter.render_layout') as render:
            with self.assertRaisesRegex(ValueError, '最大模块数量'):
                generate_plan_payload(8, 12, 8, 2, selected_modules={'B': 30}, output_dir=out)
            render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
