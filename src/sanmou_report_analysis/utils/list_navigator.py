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

from sanmou_report_analysis.utils.battle_summary import extract_battle_summary
from sanmou_report_analysis.utils.control import human_like_move
from sanmou_report_analysis.utils.geometry import (
    convert_relative_xy_to_absolute_wrt_bottom,
    get_geometry,
)
from sanmou_report_analysis.utils.image import save_image


class NavigationAborted(RuntimeError):
    """页面状态异常或卡死时抛出，立即终止采集而非继续乱点。"""


# 急停：把鼠标快速甩到屏幕左上角 → pyautogui 抛 FailSafeException 立即停止。
pyautogui.FAILSAFE = True

# --------------------------------------------------------------------------- #
# 固定坐标 / 步长（相对**客户区**，origin=客户区左上角，按客户区宽/高归一）。
# 已用 1280x665 客户区样例标定（标题栏 31px 已剔除）。仍需在你的窗口微调者标 CALIBRATE。
# --------------------------------------------------------------------------- #
# 战果页「返回」按钮可点中心（左上角弯箭头）。实测列表页同款表头箭头位于
# 客户区≈(62,24)px → (0.048,0.036)；战果页表头位置一致。如仍未返回请用战果页截图微调。
_BACK_CLICK = (0.048, 0.04)

# 单条战报相对高度：实测两条头部间距 203px / 665 ≈ 0.305。
_ENTRY_HEIGHT = 0.305

# 时间戳锚点定位（稳定，不受「连战 N 场」横幅挤动影响）：
# 每条战报右上角时间戳的 Y 即该条战报锚点；可点战报区中心 = 时间戳 Y + 偏移。
_CLICK_X = 0.46  # 点击列横向位置（中央「胜/败」区，点击容错大）
_TS_TO_CARD_OFFSET = 0.13  # 时间戳中心 → 可点战报区中心 的相对纵向偏移（实测 ≈0.13）
_MAX_CLICK_Y = 0.85  # 点击点低于此（接近底部）视为被截断，跳过、等滚动后再处理
# 玩家名相对时间戳的位置（用于去重键 ts+对战双方玩家名，锚定到时间戳 Y）：
# 实测：玩家名行在 ts_y+0.06；盟名（山海经/藏锋）在更下方。窄框只取玩家名行、排除盟名。
_NAME_DY = (0.045, 0.085)  # 玩家名行相对时间戳中心的纵向范围（不含下方盟名）
_NAME_LEFT_X = (0.30, 0.47)
_NAME_RIGHT_X = (0.55, 0.73)

# 战果(result)页底部 tab 栏区域（相对客户区）：含「战果/统计/详情/图表」。
# 实测底栏 y≈600-650px → ~[0.90,1.0]，左半部即四个标签。result 页独有，list 页没有。
_RESULT_TAB_REGION = [0.0, 0.88, 0.55, 1.0]
# 命中任意 2 个关键词即判定为 result 页（OCR 容错）。
_RESULT_TAB_KEYWORDS = ("战果", "统计", "详情", "图表", "回放", "分享", "地点", "收藏")

# 列表页时间戳所在的右侧竖条（相对客户区）。时间戳在每条战报右上角，
# 但「连战 N 场」横幅会上下挤动布局，故用整条竖带扫描、不依赖固定槽位。
_TIMESTAMP_STRIP_REGION = [0.78, 0.12, 0.97, 0.97]


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


def _has_list_timestamp(client_img: np.ndarray) -> bool:
    """扫描右侧竖条，判断是否存在「列表页时间戳」。

    不依赖固定槽位：逐行 OCR 右侧时间戳竖带，任一行的纯数字 ≥12 位（完整日期时间）
    即认为是 list 页。可容忍「连战 N 场」横幅造成的上下布局浮动。
    """
    return len(_detect_entries(client_img)) > 0


def _normalize_name(text: str) -> str:
    """归一化玩家名：仅保留中文/字母/数字，去掉空格、分隔符与 OCR 噪声。

    用于去重键，目的是「跨滚动稳定」而非语义完美。OCR 可能把分隔符「|」识别为
    丢失或杂符，这里统一剔除，使同一玩家名在不同帧得到一致结果。
    """
    import re

    return "".join(re.findall(r"[\u4e00-\u9fff0-9a-zA-Z]", text))


def _detect_entries(client_img: np.ndarray) -> list[dict]:
    """时间戳锚点定位：返回当前屏可见的战报条目（按从上到下排序）。

    每条战报右上角的时间戳 Y 即该条战报锚点，不受「连战 N 场」横幅挤动影响。
    去重键 = 时间戳 + 对战双方玩家名（排除盟名）——可区分「同一秒发生多场战斗」。
    返回列表，每项：
      {"ts": 14位数字, "names": (左名,右名), "key": (ts,左名,右名),
       "ts_y": 时间戳中心相对Y, "click": (x,y) 可点中心, "clickable": bool}
    """
    from sanmou_report_analysis.utils.ocr import ocr_text

    h, w = client_img.shape[:2]
    reg = _TIMESTAMP_STRIP_REGION
    y0_px = int(reg[1] * h)
    strip = _crop_rel(client_img, reg)

    entries: list[dict] = []
    for o in ocr_text(strip):
        digits = "".join(ch for ch in o.text if ch.isdigit())
        if len(digits) < 12:
            continue
        ts_y = (y0_px + (o.box.t + o.box.b) / 2) / h
        click_y = ts_y + _TS_TO_CARD_OFFSET
        # 读取该条双方玩家名（窄框只取玩家名行，排除盟名），并归一化
        name_box_l = [_NAME_LEFT_X[0], ts_y + _NAME_DY[0], _NAME_LEFT_X[1], ts_y + _NAME_DY[1]]
        name_box_r = [_NAME_RIGHT_X[0], ts_y + _NAME_DY[0], _NAME_RIGHT_X[1], ts_y + _NAME_DY[1]]
        raw_left = "".join(x.text for x in ocr_text(_crop_rel(client_img, name_box_l)))
        raw_right = "".join(x.text for x in ocr_text(_crop_rel(client_img, name_box_r)))
        name_left = _normalize_name(raw_left)
        name_right = _normalize_name(raw_right)
        entries.append(
            {
                "ts": digits,
                "names": (name_left, name_right),
                # 去重主键：时间戳 + 双方玩家名（同秒多场也能区分）
                "key": (digits, name_left, name_right),
                "ts_y": ts_y,
                "click": (_CLICK_X, click_y),
                "clickable": click_y <= _MAX_CLICK_Y,
            }
        )
    entries.sort(key=lambda e: e["ts_y"])
    return entries


def _is_result_page(client_img: np.ndarray) -> bool:
    """战果页判定：底部 tab 栏含「战果/统计/详情/图表…」中的 ≥2 个关键词。

    这是 result 页独有且文字清晰、易 OCR 的可靠特征，比中央半透明的「胜/败」更稳。
    """
    from sanmou_report_analysis.utils.ocr import ocr_text

    region = _crop_rel(client_img, _RESULT_TAB_REGION)
    text = "".join(o.text for o in ocr_text(region))
    hits = sum(1 for kw in _RESULT_TAB_KEYWORDS if kw in text)
    return hits >= 2


# --------------------------------------------------------------------------- #
# 页面状态检测 + 点击校验 + 急停（防止"返回失败却以为成功 → 在战果页乱点"）
# --------------------------------------------------------------------------- #
def detect_page(client_img: np.ndarray) -> str:
    """判断当前画面：'result'（战果页）/ 'list'（列表页）/ 'unknown'。

    可靠区分信号（避免两页都有的「胜/败」大字、以及「连战」横幅挤动布局造成误判）：
    - result 页：底部有「战果/统计/详情/图表」tab 栏（_is_result_page）。
    - list 页：右侧竖条任意位置存在合法日期时间戳（_has_list_timestamp，不依赖固定槽位）。
    先判 result（底部 tab 栏是其独有特征），再判 list。
    """
    if _is_result_page(client_img):
        return "result"
    if _has_list_timestamp(client_img):
        return "list"
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


def _process_entry(save_dir, entry: dict, idx: int) -> dict:
    """点进某条战报的战果页 → 提取摘要 → 返回列表页。

    entry 来自 _detect_entries（含 click 点与 key）。每步校验页面状态；
    点击无效会重试，仍失败则抛 NavigationAborted 立即中止，避免在错误页面乱点。
    """
    click_xy = entry["click"]
    key = entry["key"]

    # 1) 点击战报进入战果页，校验确实进入
    _log(f"[第{idx + 1}封] 在 list 页点击战报 {key}，尝试进入 result 页…")
    result_img = None
    for attempt in range(3):
        _check_abort_key()
        _click_relative(click_xy)
        result_img = _wait_for_page("result", timeout=4.0)
        if result_img is not None:
            _log(f"[第{idx + 1}封] ✓ 成功进入 result 页")
            break
        _log(f"[第{idx + 1}封] ✗ 点击后未进入 result 页，重试 {attempt + 1}/3")
        if save_dir is not None:
            save_image(_capture_client(), save_dir / f"fail_enter_{idx:04d}_{attempt}.png")
    if result_img is None:
        raise NavigationAborted("点击战报多次仍未进入战果页，已中止。")

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
    # 去重主键：时间戳 + 对战双方玩家名（同一秒可能多场战斗，故不能只用时间戳）
    seen: set[tuple[str, str, str]] = set()
    prev_top_ts: tuple | None = None
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

            # 时间戳锚点动态检测当前屏所有战报（不受「连战 N 场」横幅挤动影响）
            entries = _detect_entries(client_img)
            _log(f"当前屏检测到 {len(entries)} 条战报：{[e['key'] for e in entries]}")

            if not entries:
                _log("当前屏无有效战报，判定到底，停止。")
                break

            # 处理第一条「未处理且可点（未被底部截断）」的战报
            target = next(
                (e for e in entries if e["key"] not in seen and e["clickable"]), None
            )

            if target is not None:
                _log(f"处理战报：{target['key']}  点击点={target['click']}")
                summary = _process_entry(save_dir, target, len(collected))
                collected.append({"key": target["key"], "summary": summary})
                seen.add(target["key"])
                # 处理后画面/布局可能变化，重新检测，不立即滚动
                stall_rounds = 0
                continue

            # 本屏所有战报都已处理（或被底部截断）→ 上滑约 2 封继续
            top_keys = tuple(e["key"] for e in entries)
            if top_keys == prev_top_ts:
                _log("上滑后画面无变化，判定到底，停止。")
                break
            prev_top_ts = top_keys
            _log("本屏战报均已处理，上滑继续。")
            _scroll_up(2)
            stall_rounds = 0 if len(collected) > before_count else stall_rounds + 1

    except NavigationAborted as e:
        print(f"[中止] {e} 已采集 {len(collected)} 条，返回已收集结果。")
    except pyautogui.FailSafeException:
        print(f"[中止] 触发 pyautogui 角落急停。已采集 {len(collected)} 条。")

    return collected
