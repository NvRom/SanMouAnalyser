# 调试/标定工具：把程序「实际看到的客户区截图」存下来，并打印各识别区域的内容，
# 用于精确标定 list_navigator / battle_summary 中的相对坐标。
#
# 用法（在游戏中打开『战报列表』页后运行，按 s 截图，q 退出）：
#   uv run python -m sanmou_report_analysis.debug_capture

from pathlib import Path

from sanmou_report_analysis.report_collection import ensure_capture_supported_platform


def _draw_region(img, rel_box, label, color):
    import cv2

    h, w = img.shape[:2]
    x0, y0, x1, y1 = (
        int(rel_box[0] * w),
        int(rel_box[1] * h),
        int(rel_box[2] * w),
        int(rel_box[3] * h),
    )
    cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
    cv2.putText(img, label, (x0, max(y0 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)


def run_debug():
    import cv2
    import keyboard

    from sanmou_report_analysis.utils import list_navigator as ln
    from sanmou_report_analysis.utils.geometry import init_geometry
    from sanmou_report_analysis.utils.image import save_image

    out_dir = Path("./summary/debug")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("请在游戏中打开『战报列表』页。按 s 截图标定，按 q 退出。")
    while True:
        event = keyboard.read_event()
        if event.event_type != keyboard.KEY_DOWN:
            continue
        if event.name == "q":
            break
        if event.name != "s":
            continue

        init_geometry(fix_size=True)
        client = ln._capture_client()
        save_image(client, out_dir / "client_raw.png")
        print(
            f"\n[已保存] 客户区原图 -> {out_dir / 'client_raw.png'}  "
            f"尺寸={client.shape[1]}x{client.shape[0]}"
        )

        # 1) 当前 detect_page 判定
        page = ln.detect_page(client)
        print(f"[detect_page] 判定当前页面 = {page!r}")

        # 2) 时间戳锚点动态检测当前屏所有战报
        entries = ln._detect_entries(client)
        print(f"[detect_entries] 检测到 {len(entries)} 条战报：")
        for i, e in enumerate(entries):
            print(
                f"  #{i}: key={e['key']} ts_y={e['ts_y']:.3f} "
                f"click={e['click']} clickable={e['clickable']}"
            )

        # 3) 画出检测结果与关键点，存成可视化图便于核对
        vis = client.copy()
        h, w = vis.shape[:2]
        # 时间戳扫描竖带
        _draw_region(vis, ln._TIMESTAMP_STRIP_REGION, "ts_strip", (0, 200, 255))
        # result 页底部 tab 栏检测区
        _draw_region(vis, ln._RESULT_TAB_REGION, "result_tabs", (255, 0, 255))
        # 每条战报的点击点（绿圈）+ 时间戳线
        for i, e in enumerate(entries):
            cx, cy = int(e["click"][0] * w), int(e["click"][1] * h)
            color = (0, 255, 0) if e["clickable"] else (128, 128, 128)
            cv2.circle(vis, (cx, cy), 10, color, 2)
            cv2.putText(vis, f"#{i}", (cx + 12, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            ty = int(e["ts_y"] * h)
            cv2.line(vis, (int(0.78 * w), ty), (w, ty), (0, 200, 255), 1)
        # 返回按钮点（红圈）
        bx, by = ln._BACK_CLICK
        cv2.circle(vis, (int(bx * w), int(by * h)), 8, (0, 0, 255), 2)
        cv2.putText(vis, "back", (int(bx * w) + 10, int(by * h)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        save_image(vis, out_dir / "client_annotated.png")
        print(f"[已保存] 标定可视化图 -> {out_dir / 'client_annotated.png'}")
        print("请把 client_raw.png 与 client_annotated.png 发回以便校准坐标。\n")
        print("继续按 s 重新截图，或按 q 退出。")

    keyboard.unhook_all()


def main():
    ensure_capture_supported_platform()
    run_debug()


if __name__ == "__main__":
    main()
