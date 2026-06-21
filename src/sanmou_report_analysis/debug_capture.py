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
    import keyboard

    from sanmou_report_analysis.utils import list_navigator as ln
    from sanmou_report_analysis.utils.battle_summary import _LIST_REGION, _crop, parse_entry_key
    from sanmou_report_analysis.utils.geometry import init_geometry
    from sanmou_report_analysis.utils.image import save_image
    from sanmou_report_analysis.utils.ocr import ocr_text

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

        # 2) 打印两个槽位区域 OCR 到的全部文本，帮助定位时间戳/名字
        for slot in ("slot1", "slot2"):
            region = ln._crop_rel(client, ln._SLOT_REGION[slot])
            texts = [o.text for o in ocr_text(region)]
            key = parse_entry_key(region)
            print(f"[{slot}] OCR文本={texts}")
            print(f"[{slot}] 去重键(时间戳,左名,右名)={key}")

        # 3) 画出所有标定框，存成可视化图，便于核对区域是否对位
        import cv2

        vis = client.copy()
        _draw_region(vis, ln._SLOT_REGION["slot1"], "slot1", (0, 255, 0))
        _draw_region(vis, ln._SLOT_REGION["slot2"], "slot2", (0, 255, 0))
        _draw_region(vis, ln._FOLD_REGION["slot1"], "fold1", (255, 0, 0))
        _draw_region(vis, ln._FOLD_REGION["slot2"], "fold2", (255, 0, 0))
        # 返回按钮点（画个圈）
        bx, by = ln._BACK_CLICK
        cv2.circle(vis, (int(bx * vis.shape[1]), int(by * vis.shape[0])), 8, (0, 0, 255), 2)
        cv2.putText(vis, "back", (int(bx * vis.shape[1]) + 10, int(by * vis.shape[0])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        # 槽位点击点
        for slot in ("slot1", "slot2"):
            sx, sy = ln._SLOT_CLICK[slot]
            cv2.circle(vis, (int(sx * vis.shape[1]), int(sy * vis.shape[0])), 8, (0, 255, 255), 2)

        # _LIST_REGION 是相对单条战报，这里相对 slot1 画出来核对
        h1, w1 = ln._crop_rel(client, ln._SLOT_REGION["slot1"]).shape[:2]
        save_image(_crop(ln._crop_rel(client, ln._SLOT_REGION["slot1"]), _LIST_REGION["timestamp"]),
                   out_dir / "slot1_timestamp.png")

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
