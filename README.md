# 三国·谋定天下 战报自动分析工具

Sanmou Battle Analysis Tool (SBAT)  
适用于游戏《三国：谋定天下》的战报截图采集与自动化分析工具。

## 说明
由于本人近期工作比较忙，短期内没有时间优化代码，所以将目前已经基本完成的代码开源，供有兴趣的同学进一步优化，避免重复造轮子。   
下面的介绍是AI生成，如果使用中有bug或者其它问题可以微信联系：```zhj0513029```

---

## 功能概览

1. **战报采集**：自动识别游戏窗口，截取战报详情页各回合截图，并拼接为完整战报长图。
2. **战报解析**：提取武将基础信息（国籍、兵种、星级、等级、技能等），使用 OCR 识别战报文本，还原每回合的行动事件序列。
3. **战报分析**：对解析结果进行结构化统计分析，输出兵力变化、技能触发等关键数据。
4. **战果摘要批量统计**：在战报列表页自动逐条进入「战果」结算页，批量提取每场对战的胜负、阵型、双方武将、初始/最终兵力、战损等信息，汇总为 JSON / CSV。无需进入逐回合详情，速度快。

---

## 使用方法

本项目推荐使用 [uv](https://github.com/astral-sh/uv) 进行环境与依赖管理。

首次使用请先在项目根目录执行：

```bash
uv sync
```

### 完整流程（采集 + 分析）（需要管理员权限）

> 该流程依赖 Windows 窗口与输入 API（如 `win32gui`），目前仅支持 Windows。

运行 `sanmou_report_analysis.report_collection`，它会依次完成截图采集和战报分析：

```bash
uv run python -m sanmou_report_analysis.report_collection
```

1. 程序启动后，在游戏内打开目标战报详情页。
2. 按 `S` 键开始自动截图采集。
3. 采集完成后程序自动进行图像拼接，并调用分析流程。
4. 按 `Q` 键退出。

> `stage1 = True` 表示重新截图；改为 `False` 则跳过截图，仅对已有截图重新拼接。

### 仅分析（不重新截图）

直接运行 `sanmou_report_analysis.report_analysis`，对 `data/` 目录下最新的战报数据执行分析：

```bash
uv run python -m sanmou_report_analysis.report_analysis
```

> `stage1 = True` 表示重新执行元信息提取和图像解析；改为 `False` 则从已保存的 `meta_info.json` / `sentence.pkl` 中读取缓存，直接进行分析。

### 战果摘要批量统计（只统计胜负 / 战果，不进详情）（需要管理员权限）

> 该流程同样依赖 Windows 窗口与输入 API，仅支持 Windows。

运行 `sanmou_report_analysis.collect_summary`，它会在「战报列表页」自动逐条进入战果页采集摘要：

```bash
uv run python -m sanmou_report_analysis.collect_summary
```

1. 程序启动后，在游戏内打开 **战报列表页**（能看到一条条战报的那个列表，而非某一封的详情）。
2. 按 `S` 键开始：程序自动逐条点进战果页提取信息、返回、滚动到下一条，遇到折叠（连战 N 场）会先展开。
3. 处理完所有战报后自动停止，结果保存到 `summary/<自增id>/` 下：
   - `battle_summaries.json`：完整结构化数据
   - `battle_summaries.csv`：每场一行的汇总表（Excel 可直接打开）
   - `result_XXXX.png`：每场战果页原始截图
4. 按 `Q` 键退出。

> **运行中的容错与急停**：
> - 程序每次点击后会校验页面状态（是否真的进入了战果页 / 返回了列表页）。若点击无效会自动重试，连续失败则**立即停止并保留已采集结果**，不会在错误页面上乱点。
> - **急停**：采集过程中随时按 `q` 或 `esc` 可中止；或把鼠标快速甩到屏幕**左上角**（pyautogui 角落急停）也会立即停止。
> - 起步时若没检测到列表页，会直接报错提示，而不是盲目点击。

> **运行前提**：游戏窗口与标定时保持**相同的宽高比**（标定基于约 1280×665 客户区）。若窗口宽高比不同导致点击/识别错位，需按 `docs/battle_summary_plan.md` 第 0 节重新标定 `list_navigator.py` / `battle_summary.py` 中的相对坐标常量。

---

## 内部流程说明

### `sanmou_report_analysis.report_collection`（第一阶段）

| 步骤 | 说明 |
|------|------|
| `get_resolution()` | 获取游戏窗口的位置与分辨率 |
| `get_battle_images()` | 自动翻页截取各回合战报图像 |
| `stitch_images()` | 将截图拼接为完整长图，保存至 `data/<id>/` |

### `sanmou_report_analysis.report_analysis`（第二阶段）

| 步骤 | 说明 |
|------|------|
| `extract_meta_info()` | 识别武将名称、国籍、兵种、星级、技能等元数据，保存为 `meta_info.json` |
| `image_to_report()` | OCR 解析战报长图，提取每轮行动文本，保存为 `sentence.pkl` |
| `analysis()` | 对战报文本进行结构化分析，输出统计结果 |

### `sanmou_report_analysis.collect_summary`（战果摘要批量统计）

| 步骤 | 说明 |
|------|------|
| `init_geometry()` | 获取并锁定游戏窗口位置与客户区分辨率 |
| `navigate_and_collect()` | 在列表页用「固定槽位 + 固定滚动步长 + 折叠置顶」状态机逐条进入战果页，按「时间戳 + 双方名字」去重 |
| `extract_battle_summary()` | 从单张战果页截图提取胜负、阵型、双方武将、兵力、战损 |
| 汇总输出 | 落盘 `summary/<id>/battle_summaries.json` 与 `battle_summaries.csv` |

> 详细设计（坐标体系、标定值、导航状态机三分支）见 `docs/battle_summary_plan.md`。


## 注意事项

- 运行前请确保游戏已在前台运行，并且是官方提供的电脑端程序，不是安卓模拟器。
- 战报数据按自增 ID 存储于 `data/` 目录，每次新采集会自动创建新子目录。
