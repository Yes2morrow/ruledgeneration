"""Exact matching should refine the feasible mix before retrying rejected types."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '05_config_and_tools'))
import service_adapter
from module_selector import refine_bed_match, _modules_by_type


class RecommendationSearchTests(unittest.TestCase):
    def test_remainder_search_preserves_the_feasible_dominant_module_first(self):
        attempts = []
        def runner(selection, site, **kwargs):
            attempts.append(selection)
            return SimpleNamespace(success=selection.get('E') == 62, unplaced=[])
        result = refine_bed_match({'E': 64}, 190, [],
                                  _modules_by_type(['舒适型', '均衡型', '经济型']), runner)
        self.assertEqual(result, {'E': 62, 'B': 2})
        self.assertEqual(attempts, [{'E': 62, 'B': 2}])


if __name__ == '__main__':
    unittest.main()
