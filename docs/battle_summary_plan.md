# 实现方案：战报「胜负 + 战果摘要」提取功能（需求②）

## 0. 坐标体系与标定（重要）

**所有相对坐标都基于「客户区」（client area），不是整窗。** 客户区 =
`win32gui.GetClientRect`（剔除标题栏/边框），其屏幕左上角 = `ClientToScreen(0,0)` =
`absolute_x/absolute_y`。因此：

- 相对 x ∈ [0,1] = 客户区宽度比例（origin 左边）；相对 y ∈ [0,1] = 客户区高度比例（origin 顶部）。
- 点击：`convert_relative_xy_to_absolute_wrt_bottom(x,y) = (absolute_x + x*width, absolute_y + y*height)` → 屏幕绝对像素喂给 `pyautogui.click`。
- 截屏：`pyautogui.screenshot()` 抓**整屏** → 必须先按 `absolute_x/y + width/height` 裁到客户区，
  之后所有比例裁剪才与点击坐标同一体系（见 `list_navigator._capture_client`）。

### 已标定值（来自 1280×696 全窗样例，标题栏 31px → 客户区 1280×665）
| 量 | 实测像素 | 客户区相对值 | 落点 |
|---|---|---|---|
| 标题栏高度 | 31px | — | 截屏裁剪偏移 |
| 单条战报高度 | 头部间距 203px | `0.305` | `_ENTRY_HEIGHT` |
| 槽1 卡片中心 y | ≈245px | `0.322` | `_SLOT_CLICK.slot1` |
| 槽2 卡片中心 y | ≈448px | `0.627` | `_SLOT_CLICK.slot2` |
| 槽1 卡片区 | y[148,315] | `[0.04,0.176,0.93,0.427]` | `_SLOT_REGION.slot1` |
| 槽2 卡片区 | y[351,518] | `[0.04,0.481,0.93,0.732]` | `_SLOT_REGION.slot2` |
| 条内时间戳 | y157,x[1043,1180] | `[0.85,0,1,0.18]` | `_LIST_REGION.timestamp` |
| 条内左/右玩家名 | y227 | `[0.32,0.40,0.47,0.62]`/`[0.58,0.40,0.72,0.62]` | `_LIST_REGION.name_*` |

### 仍需「折叠态」「战果页」全窗截图标定（标了 CALIBRATE）
- `_EXPAND_CLICK`（折叠展开按钮）、`_FOLD_REGION`（折叠图标位置）→ 需折叠状态截图。
- `_BACK_CLICK`（战果页返回箭头）、`battle_summary._REGION`/`_HERO_SLOTS`/`_HERO_LAYOUT` → 需一张全窗战果页截图（之前那张是 1109px 裁剪图，比例略有偏差）。

---

## 1. 背景与目标

项目当前已实现 **需求①「分析战报、提取战斗细节」**：逐回合 OCR 还原事件序列、统计伤害/治疗/属性变化。

本方案新增 **需求②「战果摘要提取」**：在进入逐回合详情之前的「战果」结算页上，一次性提取本场对战的关键信息，**无需进入详情页、无需拼接长图**。

### 需要提取的字段（来自战果页一屏）
- 胜负结果（胜利 / 失败）
- 双方武将（典韦、曹操、许褚 …）：名字、国家、星级/红度、单将初始/最终兵力
- 双方战法（临危勇烈、蓄势待发、兵贵神速、坚壁清野、避其锐气、攻其不备 …）：名字、触发次数、伤害/治疗值
- 阵型（箕形阵 / 方圆阵）
- 队伍初始兵力（30000）/ 当前兵力（28435）
- 战损（891）

---

## 2. 现状与共用层（两需求复用）

复用「**截屏 + 窗口定位 + 相对坐标裁剪 + 识别**」基础层，与需求①完全共用：

| 共用能力 | 现有位置 |
|---|---|
| 窗口定位 / 分辨率 | `utils/process_info.py: get_resolution()`、`get_hwnd()` |
| 相对坐标 → 绝对像素 | `convert_relative_xy_to_absolute()`（现重复定义于 `collect_battle_image.py` 与 `slide_report.py`） |
| 区域裁剪 | `utils/data_structure.py: BoundingBox`（`.to_slice()`） |
| 截屏 | `pyautogui.screenshot()` / `utils/image.py: screenshot()` |
| OCR | `utils/ocr.py: ocr_text()` / `ocr_number()` |
| 模板匹配 | `utils/image.py: are_images_matching()`、`count_template_matches()`、`match_icon()` |
| 拟人化点击/滑动 | `utils/control.py` |
| 逐将信息 OCR | `utils/meta_info.py`（见下表逐字段复用） |

> 仅需求①专属：`utils/stitch.py`（多图拼接）、`utils/report_detail.py`（长图→事件）、`utils/analyze.py` + `utils/sentence.py`（事件分析）。需求②**不依赖**这些。

---

## 3. 字段 → 区域 → 复用映射

战果页布局（参见样例截图）：顶部状态条（阵型/总兵力/战损/胜负）+ 左右各 3 张武将立绘（含国家图标、星级、等级名、单将血条、战法触发列表）。

| 字段 | 截图区域 | 复用现有函数 | 新增工作量 |
|---|---|---|---|
| 武将名 + 等级 | 立绘底部「50 典韦」 | ✅ `meta_info.ocr_hero_level_name` | 仅需新区域坐标 |
| 国家 | 立绘左上图标 | ✅ `meta_info.match_hero_country` | 仅需新区域坐标 |
| 星级/红度 | 立绘底部金星 | ✅ `meta_info.match_n_red(img, "hero")` | 仅需新区域坐标 |
| 单将初始/最终兵力 | 立绘下血条「8845/40000」 | ✅ 思路同 `meta_info.match_hp` | 区域 + 适配 |
| 战法名 | 武将下方文字列表 | ✅ `meta_info.ocr_skill_name`（多行循环） | 多行切分 + 区域 |
| 战法触发次数/伤害 | 战法名右侧「×1 / ×11406」 | ❌ 新增 | OCR + 解析 |
| **阵型** | 顶部条中心两侧 | ❌ **全新** | 新区域 + OCR |
| **队伍总兵力/当前兵力** | 顶部「28435/30000」 | ⚠️ 思路同 `match_hp`，但为队伍总血条 | 新区域 + OCR |
| **战损** | 顶部「战损:891」 | ❌ **全新** | 新区域 + OCR |
| **胜负** | 中央金字「胜利」 + 败方立绘「溃灭」 | ❌ **全新** | 方案见下 |

### 胜负判定（三选一，可叠加做交叉校验）
1. **中心 OCR**：裁剪中央区域 OCR「胜利/失败」——最直接，复用 `ocr_text`。
2. **模板匹配**：预存金色「胜利」模板，用 `are_images_matching`——对字体光效更鲁棒。
3. **兵力推断**：某方所有武将最终兵力为 0 → 该方败——复用单将血条 OCR，附带产出战损。

> 建议：**方案 1 为主 + 方案 3 兜底校验**。

---

## 4. 新功能落点（⭐ 标注新增/修改）

### ⭐ 新增模块 `src/sanmou_report_analysis/utils/battle_summary.py`
战果页提取器，需求②的核心，与需求①详情链路解耦。

```python
# battle_summary.py 骨架
# 复用：BoundingBox / ocr_text / 以及 meta_info 的逐将函数

# ⭐ 新增：战果页专属区域字典（相对坐标，待用样例截图标定）
_summary_region = {
    "胜负":      [..],   # 中央金字
    "阵型_left": [..],   # 顶部条
    "阵型_right":[..],
    "总兵力_left":[..],  # "28435/30000"
    "总兵力_right":[..],
    "战损_left": [..],   # "战损:891"
    "战损_right":[..],
}
# 复用 collect_battle_image 的 _hero_layout 思路定位 6 张立绘

def parse_win_lose(global_img) -> str: ...        # ⭐ 新增
def parse_formation(global_img) -> tuple: ...     # ⭐ 新增
def parse_team_hp(global_img) -> tuple: ...       # ⭐ 新增
def parse_team_loss(global_img) -> tuple: ...     # ⭐ 新增
def parse_hero_summary(hero_img) -> dict: ...     # 复用 meta_info.* + 战法多行
def extract_battle_summary(global_img) -> dict:   # ⭐ 顶层聚合
    # 返回结构化 dict：{result, formation, teams:{left/right:{hp,loss,heroes:[...]}}}
```

### ⭐ 修改 `utils/collect_battle_image.py`
- 在 `collect_battle_mainpage()` 截到 `global.png` 后（约 line 188-190），调用
  `extract_battle_summary(image_summary)` 并把结果存为
  `save_dir / "battle_summary.json"`。
- **注意**：若只要战法**名字**，战果页文字已足够，可**跳过现有逐技能点击逻辑**（line 207-246），大幅提速；若仍需战法**红度/等级**，保留点击。建议加开关 `need_skill_detail: bool`。

### ⭐ 新增入口（可选）`src/sanmou_report_analysis/collect_summary.py`
仿 `slide_battle.py`：监听键盘 `s` → `get_resolution()` → 截 global → `extract_battle_summary` → 落盘 JSON/CSV。作为「只统计胜负」的独立入口，不触发详情/拼接/分析。

### ⭐ 新增 `images/` 模板（仅选模板匹配方案时）
- `images/result_victory.png`（金色「胜利」）
- `images/result_defeat.png`、`images/annihilated.png`（「溃灭」）

---

## 4.5 批量导航：从「战报列表页」逐条进入战果页（核心）

需求②要批量跑，入口是 **战报列表页**（每条战斗一行，含「连战 N 场」折叠分组）。
该列表页中央**已直接显示「胜/败」**及双方武将名/兵力，但**没有战法/阵型/战损**，
因此仍需**逐条点进战果页**提取完整字段。

### 设计：确定性「固定槽位 + 固定步长」状态机（替代动态检测）

观察：列表页每屏**稳定显示 2 封完整战报**（第 3 封只露一角），且战报**点击区域很大**。
因此点击位置可做成**相对窗口固定**，无需 `get_battle_center` 逐帧图像检测。核心规则：

- **固定槽位**：「槽位1 / 槽位2」用固定相对坐标点击（区域大，容错高）。
- **固定滚动步长**：每轮滚动量 = 恰好把已点击的 2 封移出屏幕，让新的 2 封落到**同样的固定槽位**。
- **折叠置顶**：滚动时始终把"待展开的战报"对齐到**第一个槽位**（固定位置），于是展开点击也是固定坐标；展开后从第一槽顺序处理。

整体循环：

```
init(process_info) = get_resolution()        # 一次性拿窗口长宽+初始xy（已有）
打开战报列表页
while True:
    s1 = inspect(槽位1); s2 = inspect(槽位2)   # 固定坐标 + 轻量 OCR/折叠判断

    # 分支①：槽1 折叠 → 先展开（展开后槽1 变独立战报），重新评估，不滚动
    if s1.折叠:
        点击固定展开坐标(槽位1)
        continue

    # 槽1 是普通战报 → 处理它
    点击槽位1固定坐标 → 进入战果页
    extract_battle_summary(截屏); 点返回(固定坐标)
    记录 key1=(OCR时间戳, OCR双方名字)

    # 分支②：槽2 折叠 → 只滑 1 封，让折叠战报落到槽1，下轮走分支①
    if s2.折叠:
        固定步长上滑(1 封)
        continue

    # 分支③：一般情况，槽2 也是普通战报 → 处理槽2
    if s2.有效:
        点击槽位2固定坐标 → 进入战果页
        extract_battle_summary(截屏); 点返回(固定坐标)
        记录 key2

    固定步长上滑(2 封)                          # ⭐ 步长需一次性标定
    if 滑后 槽位1.key 与上轮相同: break          # ⭐ 终止：内容未变=到底
```

> 三个分支对应滑动的三种情况：
> - **槽1 折叠** → 展开，不滑（展开后从槽1 继续）。
> - **两封都普通** → 处理两封，上滑 **2 封**。
> - **槽2 折叠** → 只处理槽1，上滑 **1 封**，确保折叠战报永远在槽1 展开。

### 边界与实现注意

1. **展开后条目数 >2**：「连战 N 场」展开成 N 封后，会连续走「分支①展开/分支③处理」逐封消化，自然收敛，无需特殊处理。
2. **如何判折叠（inspect）**：用 `images/fold.png` 在固定槽位区域做模板匹配（复用 `image.are_images_matching`）判断该槽是否折叠态。
3. **槽2 有效性**：首屏/末屏可能只有 1 封 → 用「槽位2 区域是否 OCR 到时间戳」判定该槽是否为有效战报。
4. **分支②的去重隐患**：上滑 1 封后，已处理的槽1 会下移到槽2；下轮处理完折叠再上滑 2 封时，可能再次遇到那封已处理的 → 靠 `key=(时间戳,双方名字)` 去重兜底跳过。


### 现有代码支持 vs 缺口

| 能力 | 现有 | 在新方案中 |
|---|---|---|
| 窗口几何初始化 | `process_info.get_resolution()` | ✅ 直接复用 |
| 相对→绝对坐标 | `convert_relative_xy_to_absolute()` | ✅ 复用 |
| 进入/返回点击 | `collect_battle()` 内 `pyautogui.click` | ✅ 复用 |
| 滚动 | `scroll_down()`（human_like_move） | ⚠️ 需改为**固定步长**并标定 |
| 检测条目中心 | `get_battle_center()` | ❌ **不再需要**（改固定槽位） |
| 折叠展开 | `check_folded_and_expand()`（点击被注释） | ❌ 需实现固定坐标点击 |

### ⭐ 批量导航需新增/标定的点
1. **标定固定槽位坐标**：槽位1 / 槽位2 的可点中心、返回按钮、折叠展开按钮（相对窗口，用样例截图量）。
2. **标定固定滚动步长**：使一次滚动恰好前进 2 封战报，让新战报落回原槽位。
3. **折叠置顶规则**：槽位1 若为折叠组先展开再处理；保证展开点击位置固定。
4. **安全网去重 + 终止**：OCR「时间戳+双方名字」做去重与「内容未变即到底」的终止判断（非主定位逻辑，仅校验滚动是否漂移）。

### ⚠️ 实现注意
- 游戏滚动可能有**惯性/回弹**，固定步长会漂移 → 每轮用槽位1 的 OCR key 校验是否真换页，漂移则微调或重滚。
- **首屏/末屏**可能不满 2 封 → 用「槽位2 是否 OCR 到时间戳」判断该槽是否有效。

> 建议把这套循环放进 **入口 `collect_summary.py`** 或新 `utils/list_navigator.py`，
> 与单屏提取器 `battle_summary.py` 解耦：导航器负责「翻列表+进出」，提取器负责「单屏抽字段」。

---

## 5. 建议的前置重构（可选但推荐）

`collect_battle_image.py` 与 `slide_report.py` **重复定义**了
`get_hwnd / convert_relative_xy_to_absolute / convert_*_wrt_bottom / list_to_bbox / _region_dict`。
新增需求②会进一步加剧复制。建议先抽取：

### ⭐ 新增 `utils/geometry.py`（共用坐标层）
把上述坐标换算 + `list_to_bbox` + 共享 `_region_dict` 下沉，
供 `collect_battle_image` / `slide_report` / `battle_summary` 共同 import。

> 此重构不改变行为，仅消除重复；可作为需求②落地的第 0 步。

---

## 6. 落地步骤（TODO）

1. （可选）⭐ 抽取 `utils/geometry.py`，消除坐标换算重复。
2. 用样例战果页截图，标定 `_summary_region` 各相对坐标（顶部条 4 项 + 6 立绘）。
3. ⭐ 实现 `battle_summary.py`：先做胜负 + 阵型 + 队伍兵力/战损（顶部条），再做逐将（复用 `meta_info`）+ 战法多行。
4. ⭐ 在 `collect_battle_mainpage` 接入，落盘 `battle_summary.json`；加 `need_skill_detail` 开关。
5. ⭐ 实现批量导航（`utils/list_navigator.py`）：标定固定槽位坐标 + 固定滚动步长 + 折叠置顶展开 + OCR(时间戳+双方名字)安全网去重/终止（见 4.5 节）。
6. ⭐ 加独立入口 `collect_summary.py`，串起「列表导航 → 逐条进战果页 → 提取 → 返回」。
7. 汇总多场 → CSV/xlsx（仿 `slide_report.format_csv` / `collect_data.py`），「时间戳+对战双方名字」作为每行唯一键。
8. 在 `tests/` 加样例图回归测试（OCR 字段断言）。

## 7. 验证

- 单元：对样例战果图断言各字段（胜负="胜利"、阵型="箕形阵"、初始兵力=30000、战损=891、武将名集合={典韦,曹操,许褚}）。
- 单元：对样例列表页断言「全条目检测」数量正确、折叠组能展开、时间戳 OCR 正确。
- 集成：跑独立入口，批量处理一页战报，确认逐条生成 `battle_summary.json` 且无重复/无遗漏。
- 回归：确认需求①链路（`report_collection`/`report_analysis`）行为不变。
