# 战果页「单屏摘要」提取器（需求②核心）。
#
# 输入：一张「战果」结算页截图（BGR，整张游戏客户区），见 docs/battle_summary_plan.md
#       样例截图。输出：结构化 dict（胜负 / 阵型 / 双方队伍兵力·战损 / 每个武将名·兵力·战法）。
#
# 设计原则：
# - 纯 image -> dict，不依赖窗口几何，便于用保存的截图做回归测试。
# - 所有裁剪区域都用「相对该截图宽高的比例」表示，集中在 _REGION / _HERO_SLOTS。
# - ⚠️ 下方比例为依据样例截图的初值，需用真实截图标定（搜索 CALIBRATE）。
# - 文本识别复用 utils.ocr；胜负兜底用兵力推断。

import re

import numpy as np

# 注意：OCR 依赖 paddleocr（较重）。为便于在无 OCR 环境下测试纯解析逻辑，
# ocr_text 在使用处惰性导入，而非模块顶层导入。

# --------------------------------------------------------------------------- #
# 区域定义（相对整张战果页截图的 [left, top, right, bottom] 比例） CALIBRATE
# --------------------------------------------------------------------------- #
_REGION = {
    # 中央金色「胜利 / 失败」
    "result": [0.42, 0.07, 0.58, 0.24],
    # 顶部状态条：阵型
    "formation_left": [0.30, 0.10, 0.41, 0.17],
    "formation_right": [0.59, 0.10, 0.70, 0.17],
    # 顶部状态条：队伍总兵力 "当前/初始"
    "team_hp_left": [0.0, 0.16, 0.20, 0.24],
    "team_hp_right": [0.80, 0.16, 1.0, 0.24],
    # 顶部状态条：战损
    "team_loss_left": [0.17, 0.16, 0.31, 0.24],
    "team_loss_right": [0.69, 0.16, 0.83, 0.24],
}

# 左右各 3 个武将立绘槽位（相对整张截图）。CALIBRATE
_HERO_SLOTS = {
    "left": [
        [0.005, 0.25, 0.145, 0.98],
        [0.145, 0.25, 0.285, 0.98],
        [0.285, 0.25, 0.425, 0.98],
    ],
    "right": [
        [0.575, 0.25, 0.715, 0.98],
        [0.715, 0.25, 0.855, 0.98],
        [0.855, 0.25, 0.995, 0.98],
    ],
}

# 武将立绘内部子区域（相对单张立绘 box 的比例）。CALIBRATE
_HERO_LAYOUT = {
    "name": [0.0, 0.40, 1.0, 0.50],  # 底部 "50 典韦"
    "hp": [0.0, 0.50, 1.0, 0.58],  # 血条 "8845/40000"
    "skills": [0.0, 0.60, 1.0, 1.0],  # 下方战法触发列表
}


def _crop(image: np.ndarray, box: list[float]) -> np.ndarray:
    """按相对比例 [l, t, r, b] 从图像裁剪子区域。"""
    h, w = image.shape[:2]
    left = int(box[0] * w)
    top = int(box[1] * h)
    right = int(box[2] * w)
    bottom = int(box[3] * h)
    return image[top:bottom, left:right]


def _ocr_join(image: np.ndarray) -> str:
    """OCR 区域并把多段文本按从左到右、从上到下拼接成单串。"""
    from sanmou_report_analysis.utils.ocr import ocr_text

    results = ocr_text(image)
    results = sorted(results, key=lambda r: (r.box.t, r.box.l))
    return "".join(r.text for r in results).strip()


def _parse_hp_pair(text: str) -> tuple[int, int] | None:
    """从形如 "8845/40000" 的文本里解析 (当前, 最大)。"""
    text = text.replace("／", "/").replace("O", "0").replace("o", "0")
    text = re.sub(r"[^0-9/]", "", text)
    m = re.fullmatch(r"(\d+)/(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_result(image: np.ndarray) -> str:
    """识别胜负：返回 "胜" / "败" / "未知"。

    主：OCR 中央金字关键词；兜底由调用方结合兵力推断（见 extract_battle_summary）。
    """
    text = _ocr_join(_crop(image, _REGION["result"]))
    if any(k in text for k in ("胜", "利")):
        return "胜"
    if any(k in text for k in ("败", "负", "失")):
        return "败"
    return "未知"


def parse_formation(image: np.ndarray) -> tuple[str, str]:
    """识别左右阵型，如 ("箕形阵", "方圆阵")。"""
    left = _ocr_join(_crop(image, _REGION["formation_left"]))
    right = _ocr_join(_crop(image, _REGION["formation_right"]))
    return left, right


def parse_team_hp(image: np.ndarray) -> tuple[tuple | None, tuple | None]:
    """识别左右队伍总兵力 (当前, 初始)。"""
    left = _parse_hp_pair(_ocr_join(_crop(image, _REGION["team_hp_left"])))
    right = _parse_hp_pair(_ocr_join(_crop(image, _REGION["team_hp_right"])))
    return left, right


def _parse_loss(text: str) -> int | None:
    """从形如 "战损:891" / "9035:战损" 的文本里解析出数字。"""
    digits = re.findall(r"\d+", text)
    return int(digits[0]) if digits else None


def parse_team_loss(image: np.ndarray) -> tuple[int | None, int | None]:
    """识别左右队伍战损。"""
    left = _parse_loss(_ocr_join(_crop(image, _REGION["team_loss_left"])))
    right = _parse_loss(_ocr_join(_crop(image, _REGION["team_loss_right"])))
    return left, right


def _parse_hero_name(text: str) -> tuple[int | None, str]:
    """从 "50 典韦" 解析 (等级, 名字)。"""
    text = text.strip()
    m = re.match(r"(\d{1,2})\s*(.+)", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, text


def parse_hero_card(card: np.ndarray) -> dict | None:
    """解析单个武将立绘：名字、等级、兵力、战法名列表。

    立绘若为空槽（未上阵）返回 None。
    """
    name_text = _ocr_join(_crop(card, _HERO_LAYOUT["name"]))
    if not name_text:
        return None
    level, name = _parse_hero_name(name_text)

    hp_pair = _parse_hp_pair(_ocr_join(_crop(card, _HERO_LAYOUT["hp"])))
    final_hp, initial_hp = hp_pair if hp_pair else (None, None)

    # 战法触发列表：逐行 OCR 文本，剔除右侧 ×次数/数值，仅保留战法名
    from sanmou_report_analysis.utils.ocr import ocr_text

    skills: list[str] = []
    for r in ocr_text(_crop(card, _HERO_LAYOUT["skills"])):
        token = re.split(r"[×xX]", r.text)[0].strip()
        token = re.sub(r"\d+", "", token).strip()
        if token:
            skills.append(token)

    return {
        "name": name,
        "level": level,
        "final_hp": final_hp,
        "initial_hp": initial_hp,
        "skills": skills,
    }


def parse_team_heroes(image: np.ndarray, team: str) -> list[dict]:
    """解析某一方（left/right）的最多 3 个武将。"""
    heroes = []
    for slot in _HERO_SLOTS[team]:
        card = _crop(image, slot)
        info = parse_hero_card(card)
        if info is not None:
            heroes.append(info)
    return heroes


def _infer_result_from_hp(left_hp, right_hp) -> str:
    """兜底：某方总兵力当前为 0 → 该方败。"""
    left_dead = left_hp is not None and left_hp[0] == 0
    right_dead = right_hp is not None and right_hp[0] == 0
    if right_dead and not left_dead:
        return "胜"
    if left_dead and not right_dead:
        return "败"
    return "未知"


def extract_battle_summary(image: np.ndarray) -> dict:
    """从整张战果页截图提取结构化摘要。

    返回::

        {
            "result": "胜"/"败"/"未知",   # 以左队（我方）视角
            "formation": {"left": ..., "right": ...},
            "teams": {
                "left":  {"hp": (cur, init), "loss": int, "heroes": [...]},
                "right": {"hp": (cur, init), "loss": int, "heroes": [...]},
            },
        }
    """
    result = parse_result(image)
    left_hp, right_hp = parse_team_hp(image)
    if result == "未知":
        result = _infer_result_from_hp(left_hp, right_hp)

    formation_left, formation_right = parse_formation(image)
    loss_left, loss_right = parse_team_loss(image)

    return {
        "result": result,
        "formation": {"left": formation_left, "right": formation_right},
        "teams": {
            "left": {
                "hp": left_hp,
                "loss": loss_left,
                "heroes": parse_team_heroes(image, "left"),
            },
            "right": {
                "hp": right_hp,
                "loss": loss_right,
                "heroes": parse_team_heroes(image, "right"),
            },
        },
    }


# 列表页单条战报内（相对该条战报 box）：右上角时间戳、左方名字、右方名字。
# 实测（条目 box≈[148,315]px 高167、x[51,1180] 宽1129）：
#   时间戳 y≈157→0.05, x≈[1043,1180]→[0.88,1.0]
#   左方名 "鹤|老仙" y≈227→0.47, x≈[430,545]→[0.34,0.44]
#   右方名 "青玄|懒猪" y≈227→0.47, x≈[735,820]→[0.61,0.68]
_LIST_REGION = {
    "timestamp": [0.85, 0.0, 1.0, 0.18],
    "name_left": [0.32, 0.40, 0.47, 0.62],
    "name_right": [0.58, 0.40, 0.72, 0.62],
}


def parse_entry_key(entry_image: np.ndarray) -> tuple[str, str, str]:
    """从列表页「单条战报」区域解析去重键 (时间戳, 左方名, 右方名)。"""
    ts_text = _ocr_join(_crop(entry_image, _LIST_REGION["timestamp"]))
    # 时间戳规整成 YYYY/MM/DD HH:MM:SS 里的数字串
    ts = "".join(re.findall(r"\d+", ts_text))
    name_left = _ocr_join(_crop(entry_image, _LIST_REGION["name_left"]))
    name_right = _ocr_join(_crop(entry_image, _LIST_REGION["name_right"]))
    return ts, name_left, name_right
