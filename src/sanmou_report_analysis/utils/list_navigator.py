# 战报列表页「确定性导航」状态机（需求②核心）。
#
# 思路（见 docs/battle_summary_plan.md 4.5 节）：
# - 每屏稳定显示 2 封战报，点击区域大 → 用固定相对坐标点「槽1 / 槽2」，无需图像检测。
# - 固定滚动步长：每轮恰好上滑 N 封，让新战报落回原槽位。
# - 折叠置顶：折叠战报永远在槽1 展开，于是三种滑动量 0 / 1封 / 2封。
# - OCR(时间戳+双方名字) 仅作去重/到底判断的安全网。
#
# 三分支：
#   ① 槽1 折叠      → 点固定展开坐标，不滑（展开后重新评估）。
#   ② 槽1普通,槽2折叠 → 只处理槽1，上滑 1 封（折叠落到槽1）。
#   ③ 两封都普通    → 处理两封，上滑 2 封。
#
# ⚠️ 下方固定坐标/步长为初值，需用真实窗口标定（搜索 CALIBRATE）。

import time

import numpy as np
import pyautogui

from sanmou_report_analysis.utils.battle_summary import (
    extract_battle_summary,
    parse_entry_key,
    parse_result,
)
from sanmou_report_analysis.utils.control import human_like_move
from sanmou_report_analysis.utils.geometry import (
    convert_relative_xy_to_absolute_wrt_bottom,
    get_geometry,
)
from sanmou_report_analysis.utils.image import are_images_matching, read_image, save_image


class NavigationAborted(RuntimeError):
    """页面状态异常或卡死时抛出，立即终止采集而非继续乱点。"""


# 急停：把鼠标快速甩到屏幕左上角 → pyautogui 抛 FailSafeException 立即停止。
pyautogui.FAILSAFE = True

# --------------------------------------------------------------------------- #
# 固定坐标 / 步长（相对**客户区**，origin=客户区左上角，按客户区宽/高归一）。
# 已用 1280x665 客户区样例标定（标题栏 31px 已剔除）。仍需在你的窗口微调者标 CALIBRATE。
# --------------------------------------------------------------------------- #
# 槽1 / 槽2 的可点中心。y 由实测：槽1 卡片中心 y≈245px→0.322，槽2≈448px→0.627。
_SLOT_CLICK = {
    "slot1": (0.46, 0.322),
    "slot2": (0.46, 0.627),
}
# 槽1 折叠时的「展开」按钮可点中心。CALIBRATE（需折叠态截图标定）
_EXPAND_CLICK = (0.46, 0.322)
# 战果页「返回」按钮可点中心（左上角弯箭头）。实测列表页同款表头箭头位于
# 客户区≈(62,24)px → (0.048,0.036)；战果页表头位置一致。如仍未返回请用战果页截图微调。
_BACK_CLICK = (0.048, 0.04)

# 单条战报相对高度：实测两条头部间距 203px / 665 ≈ 0.305。
_ENTRY_HEIGHT = 0.305

# 槽位区域（相对客户区 [l,t,r,b]），用于折叠判断与去重键 OCR。实测：
# 槽1 卡片 y[148,315]px→[0.176,0.427]，槽2 y[351,518]px→[0.481,0.732]；右侧留出滚动条。
_SLOT_REGION = {
    "slot1": [0.04, 0.176, 0.93, 0.427],
    "slot2": [0.04, 0.481, 0.93, 0.732],
}
# 折叠标志图标在槽位内的子区域（相对客户区）。CALIBRATE（需折叠态截图标定）
_FOLD_REGION = {
    "slot1": [0.43, 0.176, 0.50, 0.427],
    "slot2": [0.43, 0.481, 0.50, 0.732],
}

# 折叠图标模板（复用现有资源）
_FOLD_TEMPLATE_PATH = "./images/fold.png"


def _capture_client() -> np.ndarray:
    """全屏截图后裁剪到游戏客户区（BGR）。

    `pyautogui.screenshot()` 抓的是整个屏幕，而所有相对坐标都基于客户区，
    因此先按几何信息裁出客户区，使后续比例裁剪与点击坐标体系一致。
    """
    import cv2

    full = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
    info = get_geometry()
    x = int(info["absolute_x"])
    y = int(info["absolute_y"])
    w = int(info["width"])
    h = int(info["height"])
    return full[y : y + h, x : x + w]


def _crop_rel(client_img: np.ndarray, rel_box: list[float]) -> np.ndarray:
    """按相对客户区比例 [l,t,r,b] 从已裁剪的客户区图像中取子区域。"""
    h, w = client_img.shape[:2]
    left = int(rel_box[0] * w)
    top = int(rel_box[1] * h)
    right = int(rel_box[2] * w)
    bottom = int(rel_box[3] * h)
    return client_img[top:bottom, left:right]


def _log(msg: str) -> None:
    """打印带时间戳的步骤日志。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _click_relative(rel_xy: tuple[float, float], jitter: int = 6) -> None:
    """点击相对窗口坐标（带轻微随机抖动）。"""
    x, y = convert_relative_xy_to_absolute_wrt_bottom(*rel_xy)
    x += np.random.uniform(-jitter, jitter)
    y += np.random.uniform(-jitter, jitter)
    _log(f"  → 点击屏幕坐标 ({x:.0f}, {y:.0f})  [相对 {rel_xy}]")
    pyautogui.click(x=x, y=y)
    time.sleep(0.4)


def _scroll_up(n_entries: int) -> None:
    """上滑 n 封战报的距离（固定步长）。"""
    _log(f"  ↑ 上滑 {n_entries} 封战报的距离")
    distance = _ENTRY_HEIGHT * n_entries
    x0 = 0.5
    y0 = 0.7
    x1 = 0.5
    y1 = y0 - distance
    ax0, ay0 = convert_relative_xy_to_absolute_wrt_bottom(x0, y0)
    ax1, ay1 = convert_relative_xy_to_absolute_wrt_bottom(x1, y1)
    human_like_move(ax0, ay0, ax1, ay1)
    time.sleep(0.6)


def _slot_image(client_img: np.ndarray, slot: str) -> np.ndarray:
    return _crop_rel(client_img, _SLOT_REGION[slot])


def _is_folded(client_img: np.ndarray, slot: str) -> bool:
    """槽位是否折叠态：在折叠区域模板匹配 fold.png。

    are_images_matching 返回 (bool, confidence)。注意第一个值是布尔，
    不能用 `is not None` 判断（True/False 都不是 None → 永远 True）。
    """
    region = _crop_rel(client_img, _FOLD_REGION[slot])
    template = read_image(_FOLD_TEMPLATE_PATH)
    if region.size == 0 or template is None:
        return False
    matched, _conf = are_images_matching(region, template)
    return bool(matched)


def _slot_key(client_img: np.ndarray, slot: str) -> tuple[str, str, str] | None:
    """槽位去重键 (时间戳, 左名, 右名)；无有效时间戳视为空槽返回 None。"""
    key = parse_entry_key(_slot_image(client_img, slot))
    ts, _name_l, _name_r = key
    if not ts:
        return None
    return key


# --------------------------------------------------------------------------- #
# 页面状态检测 + 点击校验 + 急停（防止"返回失败却以为成功 → 在战果页乱点"）
# --------------------------------------------------------------------------- #
def detect_page(client_img: np.ndarray) -> str:
    """判断当前画面：'result'（战果页）/ 'list'（列表页）/ 'unknown'。

    ⚠️ 列表页每条战报中央**也有**「胜/败」大字，因此不能用「胜/败」区分两页。
    可靠区分信号是**时间戳**：列表页每条右上角有日期时间，战果页没有。
    故先判列表页（槽位有时间戳），再判战果页（中央有胜/败且无时间戳）。
    """
    # 列表页：任一槽位能 OCR 到有效时间戳
    if _slot_key(client_img, "slot1") is not None or _slot_key(client_img, "slot2") is not None:
        return "list"
    # 战果页：中央有金色胜/败大字，且上面已确认没有列表时间戳
    if parse_result(client_img) in ("胜", "败"):
        return "result"
    return "unknown"


def _check_abort_key() -> None:
    """检测急停键（q / esc）：按下则抛出 NavigationAborted。"""
    try:
        import keyboard

        if keyboard.is_pressed("q") or keyboard.is_pressed("esc"):
            raise NavigationAborted("用户按下急停键（q/esc），已中止采集。")
    except NavigationAborted:
        raise
    except Exception:
        pass  # keyboard 不可用时忽略，仍可用 pyautogui 角落急停


def _wait_for_page(target: str, timeout: float = 4.0, interval: float = 0.4) -> np.ndarray | None:
    """轮询等待画面切到 target 页；成功返回该帧截图，超时返回 None。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _check_abort_key()
        img = _capture_client()
        if detect_page(img) == target:
            return img
        time.sleep(interval)
    return None


def _process_slot(save_dir, slot: str, idx: int) -> dict:
    """点进某槽的战果页 → 提取摘要 → 返回列表页。

    每步都校验页面状态；点击无效会重试，仍失败则抛 NavigationAborted 立即中止，
    避免"返回失败却继续在战果页乱点"。
    """
    # 1) 点击槽位进入战果页，校验确实进入
    _log(f"[第{idx + 1}封] 在 list 页点击 {slot}，尝试进入 result 页…")
    result_img = None
    for attempt in range(3):
        _check_abort_key()
        _click_relative(_SLOT_CLICK[slot])
        result_img = _wait_for_page("result", timeout=4.0)
        if result_img is not None:
            _log(f"[第{idx + 1}封] ✓ 成功进入 result 页")
            break
        _log(f"[第{idx + 1}封] ✗ 点击 {slot} 后未进入 result 页，重试 {attempt + 1}/3")
        if save_dir is not None:
            save_image(_capture_client(), save_dir / f"fail_enter_{idx:04d}_{attempt}.png")
    if result_img is None:
        raise NavigationAborted(f"点击 {slot} 多次仍未进入战果页，已中止。")

    if save_dir is not None:
        save_image(result_img, save_dir / f"result_{idx:04d}.png")
    summary = extract_battle_summary(result_img)
    teams = summary.get("teams", {})
    left_heroes = [h.get("name") for h in teams.get("left", {}).get("heroes", [])]
    right_heroes = [h.get("name") for h in teams.get("right", {}).get("heroes", [])]
    _log(
        f"[第{idx + 1}封] result 页信息：胜负={summary.get('result')} "
        f"阵型={summary.get('formation')} 左={left_heroes} 右={right_heroes}"
    )

    # 2) 点返回，校验确实回到列表页；失败重试，仍失败则中止
    _log(f"[第{idx + 1}封] 在 result 页点击返回，尝试回到 list 页…")
    for attempt in range(3):
        _check_abort_key()
        _click_relative(_BACK_CLICK)
        if _wait_for_page("list", timeout=4.0) is not None:
            _log(f"[第{idx + 1}封] ✓ 成功返回 list 页")
            return summary
        _log(f"[第{idx + 1}封] ✗ 点击返回后未回到 list 页，重试 {attempt + 1}/3")
        if save_dir is not None:
            # 存下"点 back 之后程序看到的画面"，用于定位 back 为何失效
            cur = _capture_client()
            save_image(cur, save_dir / f"fail_back_{idx:04d}_{attempt}.png")
            _log(
                f"        当前页面判定 = {detect_page(cur)!r}"
                f"（截图已存 fail_back_{idx:04d}_{attempt}.png）"
            )
    raise NavigationAborted("点击返回多次仍未回到列表页，已中止（避免在战果页乱点）。")


def navigate_and_collect(save_dir=None, max_battles: int = 200) -> list[dict]:
    """遍历战报列表页，逐条进入战果页提取摘要。

    返回已去重的摘要列表（每项含 key 与 summary）。

    安全机制：
    - 每个动作前后校验页面状态，点击无效会重试，仍失败抛 NavigationAborted 立即停止。
    - 急停：随时按 q/esc 中止；或把鼠标快速甩到屏幕左上角（pyautogui FAILSAFE）。
    - 防卡死：连续多轮无新战报且画面无变化则判定到底/卡住并停止。
    """
    collected: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    prev_top_key: tuple | None = None
    stall_rounds = 0  # 连续无进展轮数

    try:
        # 起步必须在列表页，否则直接报错而非乱点
        _log("检查当前是否在 list 页…")
        start = _capture_client()
        start_page = detect_page(start)
        _log(f"当前页面判定 = {start_page!r}")
        if start_page != "list":
            if save_dir is not None:
                save_image(start, save_dir / "fail_start_not_list.png")
            raise NavigationAborted(
                "未检测到『战报列表』页。请先在游戏中打开战报列表页再按 s 开始。"
            )
        _log("✓ 已在 list 页，开始采集。")

        while len(collected) < max_battles:
            _check_abort_key()
            if stall_rounds >= 3:
                _log("连续多轮无新战报，判定已到底或卡住，停止采集。")
                break

            client_img = _capture_client()
            before_count = len(collected)

            # 分支①：槽1 折叠 → 展开，不滑
            if _is_folded(client_img, "slot1"):
                _log("槽1 为折叠态（连战 N 场），点击展开。")
                _click_relative(_EXPAND_CLICK)
                time.sleep(0.6)
                stall_rounds += 1  # 展开本身不算进展，但用计数兜底防死循环
                continue

            key1 = _slot_key(client_img, "slot1")
            if key1 is None:
                _log("槽1 无有效战报，判定到底，停止。")
                break  # 槽1 都没有有效战报 → 到底

            # 到底判断：滑动后槽1 内容与上轮相同
            if key1 == prev_top_key and key1 in seen:
                _log("槽1 内容与上轮相同且已处理，判定到底，停止。")
                break

            # 处理槽1
            if key1 not in seen:
                _log(f"槽1 战报：{key1}")
                summary = _process_slot(save_dir, "slot1", len(collected))
                collected.append({"key": key1, "summary": summary})
                seen.add(key1)
            else:
                _log(f"槽1 战报已处理过，跳过：{key1}")

            # 重新截屏判断槽2（处理槽1 进出后画面可能微动）
            client_img = _capture_client()

            # 分支②：槽2 折叠 → 只滑 1 封，让折叠落到槽1
            if _is_folded(client_img, "slot2"):
                _log("槽2 为折叠态，只上滑 1 封让其落到槽1。")
                prev_top_key = key1
                _scroll_up(1)
                stall_rounds = 0 if len(collected) > before_count else stall_rounds + 1
                continue

            key2 = _slot_key(client_img, "slot2")
            # 分支③：槽2 普通且有效 → 处理槽2
            if key2 is not None and key2 not in seen:
                _log(f"槽2 战报：{key2}")
                summary = _process_slot(save_dir, "slot2", len(collected))
                collected.append({"key": key2, "summary": summary})
                seen.add(key2)
            elif key2 is not None:
                _log(f"槽2 战报已处理过，跳过：{key2}")
            else:
                _log("槽2 无有效战报。")

            prev_top_key = key1
            _scroll_up(2)
            stall_rounds = 0 if len(collected) > before_count else stall_rounds + 1

    except NavigationAborted as e:
        print(f"[中止] {e} 已采集 {len(collected)} 条，返回已收集结果。")
    except pyautogui.FailSafeException:
        print(f"[中止] 触发 pyautogui 角落急停。已采集 {len(collected)} 条。")

    return collected
