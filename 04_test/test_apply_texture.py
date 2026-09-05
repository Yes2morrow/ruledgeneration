"""测试 apply_texture 是否正确显示贴图。"""
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "03_visualization"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from renderer import TextureHandler

th = TextureHandler()
img = th.images.get("moduleA2.png")
print("moduleA2 shape:", img.shape if img is not None else None)

fig, ax = plt.subplots(figsize=(8, 8))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")

# 绘制一个矩形框
ax.plot([0, 9.2, 9.2, 0, 0], [0, 0, 11.2, 11.2, 0], "r-")

# 应用贴图
th.apply_texture(ax, 0, 0, 9.2, 11.2, img, rotated=False)

ax.set_xlim(-1, 10.2)
ax.set_ylim(-1, 12.2)
ax.set_aspect("equal")
ax.axis("off")

out = str(_PROJ / "04_test" / "test_apply_texture_output.png")
fig.savefig(out, dpi=200, facecolor="white")
print("saved to", out)
