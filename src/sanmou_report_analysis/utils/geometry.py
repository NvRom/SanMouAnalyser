# Shared window geometry + relative->absolute coordinate helpers.
#
# 背景：`collect_battle_image.py` 与 `slide_report.py` 各自重复定义了
# `get_hwnd / convert_relative_xy_to_absolute / convert_*_wrt_bottom / list_to_bbox`。
# 本模块把这套「窗口几何 + 相对坐标换算」下沉为唯一来源，供新功能（战果摘要、
# 列表导航）共用。窗口长宽与初始 xy 在 `init_geometry()` 时一次性获取，之后所有
# 点击/裁剪位置都相对窗口固定。
#
# 注意：现有的两个采集模块暂未迁移到此模块（避免改动未经实机验证的采集链路）。
# 新代码应统一从这里 import；后续可逐步把旧模块也切过来。

import pygetwindow as gw

from sanmou_report_analysis.utils.data_structure import BoundingBox
from sanmou_report_analysis.utils.process_info import get_resolution, set_client_size

process_name = "三国：谋定天下"

# 标定所用的固定客户区尺寸（与 list_navigator/battle_summary 的相对坐标对应）。
CALIBRATED_CLIENT_WIDTH = 1280
CALIBRATED_CLIENT_HEIGHT = 665

# 模块级窗口几何信息（由 init_geometry 填充），结构同 process_info.get_resolution() 返回值
_process_info: dict | None = None


def init_geometry(process_info: dict | None = None, fix_size: bool = False) -> dict:
    """初始化（或刷新）窗口几何信息。

    - 传入 ``process_info`` 则直接采用；
    - 否则现场测量；若 ``fix_size=True``，先把游戏窗口客户区强制设为标定尺寸
      （``CALIBRATED_CLIENT_WIDTH x CALIBRATED_CLIENT_HEIGHT``）再测量，
      使相对坐标与标定时完全一致。

    返回填充后的几何字典。
    """
    global _process_info
    if process_info is not None:
        _process_info = process_info
        return _process_info
    if fix_size:
        set_client_size(CALIBRATED_CLIENT_WIDTH, CALIBRATED_CLIENT_HEIGHT)
    _process_info = get_resolution()
    return _process_info


def get_geometry() -> dict:
    if _process_info is None:
        raise RuntimeError("窗口几何尚未初始化，请先调用 init_geometry()")
    return _process_info


def get_hwnd(name: str = process_name):
    """返回游戏窗口句柄，找不到返回 None。"""
    try:
        all_windows = gw.getWindowsWithTitle(name)
        if all_windows:
            return all_windows[0]._hWnd
    except Exception as e:  # pragma: no cover - 环境相关
        print(f"获取窗口信息时出错: {e}")
    return None


def convert_relative_xy_to_absolute(x: float, y: float) -> tuple[float, float]:
    """相对坐标 → 屏幕绝对像素。

    与现有 ``collect_battle_image.convert_relative_xy_to_absolute`` 行为一致：
    - ``primary_axis == "width"``：x/y 均以窗口左上角为原点、按宽度归一。
    - 否则（高度主轴）：x 以窗口水平中心为原点、按 ``height * 1.75`` 缩放；
      y 以窗口顶部为原点、按高度归一。
    """
    info = get_geometry()
    if info["primary_axis"] == "width":
        absolute_x = info["absolute_x"] + x * info["width"]
        absolute_y = info["absolute_y"] + y * info["width"] / info["wh_ratio"]
    else:
        absolute_x = info["absolute_x"] + info["width"] / 2 + x * info["height"] * 1.75
        absolute_y = info["absolute_y"] + y * info["height"]
    return absolute_x, absolute_y


def convert_relative_xy_to_absolute_wrt_bottom(x: float, y: float) -> tuple[float, float]:
    """相对坐标 → 绝对像素（x、y 均以窗口左上角为原点、按各自维度归一）。"""
    info = get_geometry()
    absolute_x = info["absolute_x"] + x * info["width"]
    absolute_y = info["absolute_y"] + y * info["height"]
    return absolute_x, absolute_y


def list_to_bbox(box) -> BoundingBox:
    """把相对坐标 ``[left, top, right, bottom]`` 转成绝对像素的 BoundingBox。"""
    left, top, right, bottom = box
    new_l, new_t = convert_relative_xy_to_absolute(left, top)
    new_r, new_b = convert_relative_xy_to_absolute(right, bottom)
    return BoundingBox((new_l, new_t, new_r, new_b))
