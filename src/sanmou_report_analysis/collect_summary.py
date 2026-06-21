# 需求②入口：批量「只统计战报胜负 / 战果摘要」。
#
# 流程：按 s 触发 → 初始化窗口几何 → 遍历战报列表页逐条进战果页提取摘要
#       → 汇总落盘 JSON + CSV。与需求①（详情/拼接/分析）完全解耦。
#
# 运行：uv run python -m sanmou_report_analysis.collect_summary
# 仅支持 Windows（依赖 win32 / 截屏 / 鼠标控制）。

import csv
import json
from pathlib import Path

from sanmou_report_analysis.report_collection import ensure_capture_supported_platform


def _flatten_summary(key, summary: dict) -> dict:
    """把一条战果摘要拍平成 CSV 行。"""
    ts, name_left, name_right = key
    row = {
        "时间戳": ts,
        "左方": name_left,
        "右方": name_right,
        "胜负": summary.get("result"),
        "左阵型": summary.get("formation", {}).get("left"),
        "右阵型": summary.get("formation", {}).get("right"),
    }
    for side in ("left", "right"):
        team = summary.get("teams", {}).get(side, {})
        hp = team.get("hp")
        prefix = "左" if side == "left" else "右"
        row[f"{prefix}玩家"] = team.get("player")
        row[f"{prefix}当前兵力"] = hp[0] if hp else None
        row[f"{prefix}初始兵力"] = hp[1] if hp else None
        row[f"{prefix}战损"] = team.get("loss")
        for i, hero in enumerate(team.get("heroes", []), start=1):
            row[f"{prefix}武将{i}"] = hero.get("name")
            row[f"{prefix}武将{i}红度"] = hero.get("n_red")
            row[f"{prefix}武将{i}战法"] = "/".join(hero.get("skills", []))
    return row


def _save_results(results: list[dict], save_dir: Path) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)

    json_path = save_dir / "battle_summaries.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    rows = [_flatten_summary(tuple(r["key"]), r["summary"]) for r in results]
    if rows:
        fieldnames: list[str] = []
        for row in rows:
            for k in row:
                if k not in fieldnames:
                    fieldnames.append(k)
        csv_path = save_dir / "battle_summaries.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(f"已保存 {len(results)} 条战报摘要到 {save_dir}")


def collect_summary() -> None:
    import keyboard

    from sanmou_report_analysis.utils.geometry import init_geometry
    from sanmou_report_analysis.utils.list_navigator import navigate_and_collect
    from sanmou_report_analysis.utils.process_info import check_dpi_scaling

    check_dpi_scaling()

    root_dir = Path("./summary")
    root_dir.mkdir(parents=True, exist_ok=True)
    idx_list = [int(p.name) for p in root_dir.iterdir() if p.name.isdigit()]
    current_idx = max(idx_list) + 1 if idx_list else 0
    save_dir = root_dir / str(current_idx)

    print("请在游戏中打开『战报列表』页。按 s 开始，按 q 退出。")
    while True:
        event = keyboard.read_event()
        if event.event_type != keyboard.KEY_DOWN:
            continue
        if event.name == "s":
            init_geometry(fix_size=True)
            results = navigate_and_collect(save_dir)
            _save_results(results, save_dir)
            print("采集完成，退出程序。")
            break
        if event.name == "q":
            break
    keyboard.unhook_all()


def main() -> None:
    ensure_capture_supported_platform()
    collect_summary()


if __name__ == "__main__":
    main()
