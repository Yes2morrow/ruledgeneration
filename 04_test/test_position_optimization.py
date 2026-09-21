"""Fast candidate filtering must preserve the reference geometric decisions."""
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '05_config_and_tools'))
import service_adapter
from config_loader import get_group_defs, load_module_config
from position_finder import (find_best_position, calculate_group_size, _generate_candidates,
                             can_place, _score, _pair_spacing)


class PositionOptimizationTests(unittest.TestCase):
    def test_fast_filter_and_scoring_preserve_reference_best_position(self):
        rng = random.Random(20260922)
        sites = [[(0,0),(20,0),(20,20),(0,20)],
                 [(-5,-3),(15,-3),(15,17),(-5,17)],
                 [(0,0),(10,0),(10,10),(7,10),(7,3),(3,3),(3,10),(0,10)],
                 [(0,5),(5,0),(15,0),(20,5),(15,15),(5,15)]]
        for site in sites:
            for gap in [0, 1.5]:
                group = dict(get_group_defs('B')[-1], external_spacing={
                    'horizontal_gap_m':gap, 'vertical_gap_m':gap+.2})
                config = load_module_config('B')
                placed = [SimpleNamespace(rect=(rng.randrange(10),rng.randrange(10),2,4),
                                          _group_def=group) for _ in range(5)]
                reference = []
                for rotated in [False,True]:
                    w,h = calculate_group_size(group,config,rotated)
                    for x,y in _generate_candidates(placed,site,w,h,group):
                        if can_place((x,y,w,h),placed,site,group):
                            reference.append((x,y,rotated,w,h))
                expected = min(reference,key=lambda c:_score(c,placed,site,group)) if reference else None
                self.assertEqual(find_best_position(group,config,placed,site),expected)

    def test_cached_alignment_scores_match_at_tolerance_edges(self):
        group = {'external_spacing':{'horizontal_gap_m':0,'vertical_gap_m':0}}
        placed = [SimpleNamespace(rect=(x,y,2,4),_group_def=group)
                  for x,y in [(0,0),(.0000001,5),(4,0),(8,10)]]
        context = (sorted({v for p in placed for v in (p.rect[0],p.rect[0]+p.rect[2])}),
                   sorted({v for p in placed for v in (p.rect[1],p.rect[1]+p.rect[3])}),
                   [_pair_spacing(group,p._group_def) for p in placed])
        for x in [0,.0499999,.05,.05000001,1.95,2,4.05,8]:
            for y in [0,.05,4.05,5,9.95]:
                candidate = (x,y,False,2,4)
                self.assertEqual(_score(candidate,placed,[],group,context),
                                 _score(candidate,placed,[],group))


if __name__ == '__main__':
    unittest.main()
