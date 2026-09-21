"""布局可视化渲染器 - 将 LayoutResult 渲染为带贴图的 PNG。

绘制层次:
  1. 场地多边形(黑色外框)
  2. 道路区域(浅灰填充)
  3. 群组贴图(按 group_type / single_texture 选择)
  4. 群组外框(大框, 模块色, 粗线)
  5. 模块小框(细线, 与旧项目一致)
  6. 床位多边形(半透明填充 + 床头方向标记 + bed_id)
  7. 图例与指标(仅 show_labels=True 时)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")  # 无 GUI 后端
import matplotlib.image as mpimg  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import rc_context  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon, Rectangle, PathPatch
from matplotlib.path import Path as MplPath  # noqa: E402

_PROJ = Path(__file__).resolve().parents[1]
if str(_PROJ / "02_placement_generation") not in sys.path:
    sys.path.insert(0, str(_PROJ / "02_placement_generation"))

from geometry import BedInstance, LayoutResult, PlacedGroup, PlacedModule, RoadArea, polygon_bbox, normalize_rotation  # noqa: E402

# 中文字体配置。
# 注意: 不使用 plt.rcParams 全局赋值(那是进程级共享状态, 多线程渲染时会互相干扰),
# 改为在每次渲染时用 rc_context 局部生效。
_CJK_FONT_RC = {
    "font.sans-serif": ["SimHei", "Microsoft YaHei", "Noto Sans CJK SC", "DejaVu Sans"],
    "axes.unicode_minus": False,
}

_TYPE_COLORS = {
    "舒适型": "#8B0000",
    "经济型": "#006400",
    "均衡型": "#00008B",
}
_DIR_ARROW = {"north": "↑", "south": "↓", "east": "→", "west": "←"}


# --------------------------------------------------------------------------- #
# 贴图处理
# --------------------------------------------------------------------------- #
class TextureHandler:
    """加载并应用 textures/ 目录下的模块贴图。"""

    def __init__(self, textures_dir: Optional[Path] = None):
        if textures_dir is None:
            textures_dir = Path(__file__).resolve().parent / "textures"
        self.textures_dir = textures_dir
        self.images: Dict[str, np.ndarray] = {}
        self._load_images()

    def _prepare(self, image: np.ndarray) -> np.ndarray:
        """将带透明通道的 PNG 预合成到白色背景上, 避免透明像素显示成灰色。"""
        arr = np.asarray(image).astype(np.float32)
        if arr.max() > 1.0:
            arr /= 255.0
        if len(arr.shape) == 3 and arr.shape[2] == 4:
            rgb = arr[..., :3]
            alpha = arr[..., 3:4]
            white = np.ones_like(rgb)
            return np.clip(rgb * alpha + white * (1.0 - alpha), 0.0, 1.0)
        if len(arr.shape) == 3 and arr.shape[2] >= 3:
            return np.clip(arr[..., :3], 0.0, 1.0)
        return np.clip(arr, 0.0, 1.0)

    def _load_images(self) -> None:
        if not self.textures_dir.exists():
            print(f"[警告] 贴图目录不存在: {self.textures_dir}")
            return
        for filepath in sorted(self.textures_dir.glob("*.png")):
            try:
                self.images[filepath.name] = self._prepare(mpimg.imread(str(filepath)))
            except Exception as e:
                print(f"[失败] 加载贴图 {filepath.name}: {e}")

    def _try_filenames(self, *names: str) -> Optional[np.ndarray]:
        """按候选文件名顺序查找已加载贴图。"""
        for name in names:
            if name in self.images:
                return self.images[name]
        return None

    def get_module_texture(self, module: PlacedModule) -> Optional[np.ndarray]:
        """Return one module only; never stretch a single texture across a group.

        A's legacy atlas contains four modules. Its upper-right quadrant is the
        unmirrored module (matching A_group_two's row=1, col=1 arrangement).
        Other atlases must not be used as a fallback for a missing single.
        """
        visual = (module.config or {}).get("visual") or {}
        filename = visual.get("single_texture", "")
        image = self._try_filenames(filename, filename.replace("_", ""))
        if image is not None:
            return image
        if module.module_id == "A":
            atlas = self._try_filenames("moduleA2.png")
            if atlas is not None:
                height, width = atlas.shape[:2]
                return atlas[:height // 2, width // 2:]
        return None

    def get_group_texture(self, group: PlacedGroup) -> Optional[Tuple[np.ndarray, bool]]:
        """获取群组贴图及是否需要旋转。

        返回 (image_array, texture_already_rotated)。
        当 group.rotated=True 时, 若贴图为横向构图需要顺时针旋转 90 度。
        """
        module_id = group.module_id
        group_type = group.group_type
        first_config = group.modules[0].config if group.modules else {}
        visual = first_config.get("visual") or {}

        # 1. 按 group_type 精确匹配
        for tex in visual.get("textures", []) or []:
            if tex.get("group_type") == group_type:
                img = self._try_filenames(tex.get("file", ""))
                if img is not None:
                    return img, False

        # 2. 单体默认贴图(兼容带下划线与不带下划线的文件名)
        single = visual.get("single_texture")
        if single:
            img = self._try_filenames(single, single.replace("_", ""))
            if img is not None:
                return img, False

        # 3. 回退到旧项目映射(优先使用组合贴图)
        fallback_map = {
            ("A", "A_group_one"): ("moduleA1.png", False),
            ("A", "A_group_two"): ("moduleA2.png", False),
            ("A", "A_group_three"): ("moduleA3.png", False),
            ("B", "B0"): ("moduleB.png", False),
            ("B", "B_compact"): ("moduleB.png", False),
            ("B", "B_quad_cluster"): ("moduleB1.png", False),
            ("B", "B_row_pair"): ("moduleB2.png", False),
            ("B", "B_single"): ("moduleBsingle.png", False),
            ("C", "C_quad"): ("moduleCsingle.png", False),
            ("C", "C_pair"): ("moduleCsingle.png", False),
            ("D", "D0"): ("moduleD.png", False),
            ("D", "D1"): ("moduleD1.png", False),
            ("D", "D_single"): ("moduleDsingle.png", False),
            ("E", "E_pair"): ("moduleE1.png", False),
            ("E", "E_single"): ("moduleEsingle.png", False),
            ("F", "F1"): ("moduleF1.png", False),
            ("F", "F_single"): ("moduleFsingle.png", False),
            ("G", "G_single"): ("moduleGsingle.png", False),
        }
        if (module_id, group_type) in fallback_map:
            filename, _ = fallback_map[(module_id, group_type)]
            img = self._try_filenames(filename)
            if img is not None:
                return img, False

        # 4. 最后尝试 module_id + single / 通用文件名
        generic = {
            "A": "moduleA1.png",
            "B": "moduleB.png",
            "C": "moduleCsingle.png",
            "D": "moduleD.png",
            "E": "moduleEsingle.png",
            "F": "moduleFsingle.png",
            "G": "moduleGsingle.png",
        }
        img = self._try_filenames(generic.get(module_id, ""))
        if img is not None:
            return img, False

        return None, False

    def apply_texture(
        self,
        ax,
        x: float,
        y: float,
        width: float,
        height: float,
        image: np.ndarray,
        rotated: bool = False,
        mirror: str = "none",
        alpha: float = 1.0,
        rotation: Optional[int] = None,
    ) -> None:
        """在指定矩形区域内显示贴图, 支持整体旋转与模块镜像。"""
        img = image
        m = mirror or "none"
        # 先按模块 mirror 翻转(在贴图自身坐标系)
        if m in ("horizontal", "both"):
            img = np.fliplr(img)
        if m in ("vertical", "both"):
            img = np.flipud(img)
        angle = normalize_rotation(rotation if rotation is not None else (90 if rotated else 0))
        img = np.rot90(img, k=-(angle // 90))
        ax.imshow(
            img,
            extent=[x, x + width, y, y + height],
            aspect="auto",
            alpha=alpha,
            interpolation="nearest",
            origin="upper",
            zorder=2,
        )


# 贴图是只读资源, 进程内共享一份即可。
# 原实现每次 render_layout 都 new TextureHandler(), 每请求重复读取 16 张 PNG 约 0.27s。
_TEXTURE_CACHE: Optional["TextureHandler"] = None
_TEXTURE_LOCK = threading.Lock()
# pyplot and rc_context share process-wide state, including the current figure.
_RENDER_LOCK = threading.Lock()


def get_texture_handler() -> "TextureHandler":
    """返回进程级贴图缓存(双重检查锁, 线程安全)。"""
    global _TEXTURE_CACHE
    if _TEXTURE_CACHE is None:
        with _TEXTURE_LOCK:
            if _TEXTURE_CACHE is None:
                _TEXTURE_CACHE = TextureHandler()
    return _TEXTURE_CACHE


def _module_color(pm: PlacedModule) -> str:
    visual = (pm.config or {}).get("visual", {}) or {}
    color = visual.get("color")
    if color:
        return color
    mtype = (pm.config or {}).get("type")
    return _TYPE_COLORS.get(mtype, "#444444")


def _lighten(hex_color: str, factor: float = 0.6) -> tuple:
    """hex 颜色转浅色 rgba。"""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        r, g, b = 136, 136, 136
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return (r / 255, g / 255, b / 255, 0.45)


def _figure_size(length_m: float, width_m: float):
    """根据场地长宽比计算图像尺寸(英寸), 基准12英寸, 限制在6~16之间。"""
    aspect = max(length_m, 1e-6) / max(width_m, 1e-6)
    base = 12
    if aspect >= 1:
        fw, fh = base, base / aspect
    else:
        fh, fw = base, base * aspect
    min_size, max_size = 6, 16
    for idx, val in enumerate((fw, fh)):
        if val < min_size:
            scale = min_size / val
            fw, fh = fw * scale, fh * scale
        elif val > max_size:
            scale = max_size / val
            fw, fh = fw * scale, fh * scale
    return fw, fh


def _group_texture_keys(module_id: str, group_type: str) -> bool:
    """判断某 group_type 是否使用组合贴图(整张 group 一张图)。"""
    combo_types = {
        "A_group_one",
        "A_group_two",
        "A_group_three",
        "B0",
        "B_compact",
        "B_quad_cluster",
        "B_row_pair",
        "B_single",
    }
    return group_type in combo_types


def _render_layout_inner(
    result: LayoutResult,
    output_path,
    show_labels: bool = True,
    show_roads: bool = True,
    show_structure: bool = True,
) -> str:
    """渲染布局为 PNG, 返回输出路径。

    参数:
        show_labels: 是否显示文字标签(模块/床位编号等)。
        show_roads:  是否显示道路/过道区域(灰色填充)。
        show_structure: 是否显示模块结构(群组外框、模块小框、床位多边形)。
                        False 时只保留场地边框与贴图, 适合作为默认展示图;
                        True 时显示完整结构, 适合开发校对。
    """
    site_minx, site_miny, site_maxx, site_maxy = polygon_bbox(list(result.site_polygon))
    fig_w, fig_h = _figure_size(site_maxx - site_minx, site_maxy - site_miny)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    texture_handler = get_texture_handler()

    # 场地多边形：画黑色边框
    site = list(result.site_polygon)
    ax.add_patch(
        MplPolygon(
            site,
            closed=True,
            fill=False,
            edgecolor="black",
            linewidth=1.5,
            label="场地",
            zorder=5,
        )
    )

    # Public roads exclude entire module footprints; internal aisles are explicit.
    # Narrow or disconnected open space is shown separately from usable roads.
    if show_structure and show_roads:
        for road in result.roads:
            if road.source not in ("walkable", "module", "nonroad_open_area"):
                continue
            rings = [road.polygon_m] + road.holes_m
            paths = [MplPath(list(ring) + [ring[0]], closed=True) for ring in rings if len(ring) >= 3]
            if not paths:
                continue
            ax.add_patch(PathPatch(
                MplPath.make_compound_path(*paths),
                facecolor={"walkable":"#87CEEB", "module":"#8DD4A9", "nonroad_open_area":"#F7CA76"}[road.source],
                edgecolor="none", alpha=0.45, zorder=2.5,
            ))

    # 群组与模块
    for gi, g in enumerate(result.groups):
        mod_color = _module_color(g.modules[0]) if g.modules else "#444444"

        # 贴图
        for m in g.modules:
            tex_image = texture_handler.get_module_texture(m)
            if tex_image is not None:
                texture_handler.apply_texture(
                    ax, m.x, m.y, m.occ_length_m, m.occ_width_m,
                    tex_image, rotation=m.rotation, mirror=m.mirror,
                )
            elif not show_structure:
                # Missing artwork must not silently hide real beds.
                from geometry import transform_module_polygon
                for bed in m.config.get("beds_layout", []):
                    polygon, _ = transform_module_polygon(
                        bed["polygon"], m.length_mm, m.width_mm, m.mirror, m.rotation
                    )
                    ax.add_patch(MplPolygon(
                        [(m.x + x / 1000, m.y + y / 1000) for x, y in polygon],
                        closed=True, facecolor="white", edgecolor="black", linewidth=0.8,
                    ))

        if show_structure:
            # 群组大框
            ax.add_patch(
                Rectangle(
                    (g.x, g.y),
                    g.length_m,
                    g.width_m,
                    fill=False,
                    edgecolor=mod_color,
                    linewidth=2.0,
                    linestyle="-",
                    zorder=3,
                )
            )
            if show_labels:
                ax.text(
                    g.x + 0.1,
                    g.y + g.width_m - 0.1,
                    f"{g.module_id}/{g.group_type}{' (rot)' if g.rotated else ''}",
                    fontsize=7,
                    color=mod_color,
                    verticalalignment="top",
                    zorder=4,
                )

            # 模块小框
            for m in g.modules:
                ax.add_patch(
                    Rectangle(
                        (m.x, m.y),
                        m.occ_length_m,
                        m.occ_width_m,
                        fill=False,
                        edgecolor=mod_color,
                        linewidth=0.8,
                        linestyle="--",
                        alpha=0.8,
                        zorder=3,
                    )
                )

    # 床位(仅结构校对图显示)
    if show_structure:
        for bed in result.beds:
            color = "#666666"
            for g in result.groups:
                if g.module_id == bed.module_id and g.modules:
                    color = _module_color(g.modules[0])
                    break
            ax.add_patch(
                MplPolygon(
                    bed.polygon_m,
                    closed=True,
                    facecolor=_lighten(color),
                    edgecolor=color,
                    linewidth=0.6,
                    zorder=4,
                )
            )
            if show_labels:
                bminx, bminy, bmaxx, bmaxy = polygon_bbox(bed.polygon_m)
                cx, cy = (bminx + bmaxx) / 2, (bminy + bmaxy) / 2
                ax.text(
                    cx,
                    cy,
                    f"{bed.bed_id}{_DIR_ARROW.get(bed.head_direction, '')}",
                    fontsize=6,
                    ha="center",
                    va="center",
                    color=color,
                    zorder=5,
                )

    # 未放置提示(仅结构校对图显示)
    if show_structure and result.unplaced:
        note = "未放置: " + ", ".join(
            f"{u['module_id']}/{u['group_type']}x{u['module_count']}" for u in result.unplaced
        )
        ax.text(0.5, 0.02, note, transform=ax.transAxes, fontsize=8, color="red", ha="center")

    # 视野与比例 - 使用场地 bbox, 避免被床位循环覆盖
    pad = max(site_maxx - site_minx, site_maxy - site_miny) * 0.05
    ax.set_xlim(site_minx - pad, site_maxx + pad)
    ax.set_ylim(site_miny - pad, site_maxy + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

    output_path = str(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    # 必须用 fig.savefig 而不是 plt.savefig:
    # plt.savefig 保存的是 pyplot 的"全局当前 figure", 多线程并发渲染时会互相覆盖,
    # 导致 A 用户的图被写成 B 用户的图(实测 8 路并发渲染同一布局产出 4 种字节流)。
    fig.savefig(output_path, dpi=200, facecolor="white", edgecolor="none")
    plt.close(fig)
    return output_path


def render_layout(
    result: LayoutResult,
    output_path,
    show_labels: bool = True,
    show_roads: bool = True,
    show_structure: bool = True,
) -> str:
    """渲染布局为 PNG(线程安全入口)。

    字体配置通过 rc_context 局部生效, 不污染进程级 rcParams。
    """
    with _RENDER_LOCK, rc_context(_CJK_FONT_RC):
        return _render_layout_inner(
            result, output_path,
            show_labels=show_labels,
            show_roads=show_roads,
            show_structure=show_structure,
        )
