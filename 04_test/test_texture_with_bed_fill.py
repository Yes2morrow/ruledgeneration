"""测试贴图 + 床位半透明填充的叠加效果。"""
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "03_visualization"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon, Rectangle
import numpy as np
from renderer import TextureHandler, _lighten

th = TextureHandler()
img = th.images.get("moduleA2.png")

fig, ax = plt.subplots(figsize=(8, 8))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

# 应用贴图
th.apply_texture(ax, 0, 0, 9.2, 11.2, img, rotated=False)

# 添加半透明床位填充（模拟A模块的3个床位）
color = "#8B0000"
beds = [
    [(0, 3.6), (2.3, 3.6), (2.3, 5.6), (0, 5.6)],
    [(2.3, 3.6), (4.6, 3.6), (4.6, 5.6), (2.3, 5.6)],
    [(2.6, 0), (4.6, 0), (4.6, 2.3), (2.6, 2.3)],
]
for bed in beds:
    ax.add_patch(MplPolygon(bed, closed=True, facecolor=_lighten(color), edgecolor=color, linewidth=0.6, zorder=4))

# 添加模块框
ax.add_patch(Rectangle((0, 0), 9.2, 11.2, fill=False, edgecolor=color, linewidth=2.0, zorder=3))

ax.set_xlim(-1, 10.2)
ax.set_ylim(-1, 12.2)
ax.set_aspect("equal")
ax.axis("off")

out = str(_PROJ / "04_test" / "test_texture_with_bed_fill_output.png")
fig.savefig(out, dpi=200, facecolor="white")
print("saved to", out)
