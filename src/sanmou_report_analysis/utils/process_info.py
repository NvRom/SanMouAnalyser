import mss
import win32con
import win32gui

process_name = "三国：谋定天下"


def check_dpi_scaling() -> float:
    """返回主显示器的缩放比例（1.0 = 100%）。

    本工具的固定坐标/截屏假设系统缩放为 100%。若不是，`pyautogui` 点击像素
    与 `win32gui` 量到的像素会错位，导致点击/识别偏移。非 100% 时打印告警。
    """
    import contextlib
    import ctypes

    with contextlib.suppress(Exception):
        # Per-monitor DPI aware，避免拿到被系统虚拟化的 96
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    scale = 1.0
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        logpixelsx = 88  # win32con.LOGPIXELSX
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, logpixelsx)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        scale = dpi / 96.0
    except Exception as e:  # pragma: no cover - 环境相关
        print(f"无法获取DPI信息: {e}")
        return scale

    if abs(scale - 1.0) > 1e-3:
        print(
            f"⚠️ 检测到显示缩放为 {scale:.0%}（DPI={dpi}）。"
            "本工具按 100% 缩放标定，非 100% 可能导致点击/识别坐标错位。"
            "建议将系统显示缩放设为 100% 后再运行。"
        )
    else:
        print(f"显示缩放 100%（DPI={dpi}），坐标体系正常。")
    return scale


def set_client_size(client_width=1280, client_height=665, x=0, y=0, name=process_name):
    """把游戏窗口移动到 (x, y) 并把**客户区**调整为固定大小。

    标定基于客户区尺寸，因此这里固定的是客户区（不含标题栏/边框），
    通过「窗口外框 - 客户区」的差值反推需要设置的外框尺寸。

    返回 True 表示成功；窗口不存在返回 False。
    """
    hwnd = win32gui.FindWindow(None, name)
    if not hwnd:
        print(f"未找到游戏窗口: {name}")
        return False

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    # 外框矩形与客户区矩形之差 = 标题栏 + 边框占用的像素
    win_l, win_t, win_r, win_b = win32gui.GetWindowRect(hwnd)
    _, _, cli_w, cli_h = win32gui.GetClientRect(hwnd)
    chrome_w = (win_r - win_l) - cli_w
    chrome_h = (win_b - win_t) - cli_h

    target_w = client_width + chrome_w
    target_h = client_height + chrome_h

    win32gui.MoveWindow(hwnd, x, y, target_w, target_h, True)
    win32gui.SetForegroundWindow(hwnd)
    return True


def get_resolution():
    hwnd = win32gui.FindWindow(None, process_name)

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    _, _, client_width, client_height = win32gui.GetClientRect(hwnd)
    client_left_top = win32gui.ClientToScreen(hwnd, (0, 0))
    client_right_bottom = win32gui.ClientToScreen(hwnd, (client_width, client_height))

    (client_left_top[0] + client_right_bottom[0]) // 2
    (client_left_top[1] + client_right_bottom[1]) // 2

    with mss.mss() as sct:
        monitor = sct.monitors[1]

    relative_x = client_left_top[0] - monitor["left"]
    relative_y = client_left_top[1] - monitor["top"]

    windows_info = {
        "title": process_name,
        "width": client_width,
        "height": client_height,
        "absolute_x": client_left_top[0],
        "absolute_y": client_left_top[1],
        "monitor_width": monitor["width"],
        "monitor_height": monitor["height"],
        "relative_x": relative_x,
        "relative_y": relative_y,
    }

    width = windows_info["width"]
    height = windows_info["height"]

    wh_ratio = width / height if height != 0 else 0
    windows_info["wh_ratio"] = wh_ratio
    windows_info["primary_axis"] = "height"

    # position_info = info  # 赋值给全局变量
    print(windows_info)
    return windows_info
