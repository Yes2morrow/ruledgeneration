"""测试 TextureHandler 能否正确加载并返回贴图。"""
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "03_visualization"))
sys.path.insert(0, str(_PROJ / "01_pre_selection"))

from renderer import TextureHandler
from config_loader import load_module_config

th = TextureHandler()
print("已加载贴图:", sorted(th.images.keys()))

# 模拟一个 PlacedGroup 的最小结构
class FakeModule:
    def __init__(self, config):
        self.config = config

class FakeGroup:
    def __init__(self, module_id, group_type, modules):
        self.module_id = module_id
        self.group_type = group_type
        self.modules = modules
        self.rotated = False

for mid in ["A", "B", "C", "D", "E", "F", "G"]:
    cfg = load_module_config(mid)
    g = FakeGroup(mid, f"{mid}_unknown", [FakeModule(cfg)])
    img, _ = th.get_group_texture(g)
    print(f"  {mid}: img={'有' if img is not None else '无'}")

# 特定 group_type
for mid, gt in [("A", "A_group_one"), ("A", "A_group_two"), ("C", "C_pair"), ("E", "E_pair")]:
    cfg = load_module_config(mid)
    g = FakeGroup(mid, gt, [FakeModule(cfg)])
    img, _ = th.get_group_texture(g)
    print(f"  {mid}/{gt}: img={'有' if img is not None else '无'}")
