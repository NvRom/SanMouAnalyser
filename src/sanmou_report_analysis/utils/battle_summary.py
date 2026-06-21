# 战果页「单屏摘要」提取器（需求②核心）。
#
# 输入：一张「战果」结算页截图（BGR，整张游戏客户区）。
# 输出：结构化 dict（胜负 / 阵型 / 双方玩家名·队伍兵力·战损 / 每个武将名·兵力·红度·战法）。
#
# 坐标已用真实 1280x665 result 页截图标定（summary/6/result_0000_0.png）。
# 设计原则：能模板/颜色判断的不用 OCR（如红度按颜色数）；OCR 只用于文字。

import re

import numpy as np

# 注意：OCR 依赖 paddleocr（较重）。为便于在无 OCR 环境下测试纯解析逻辑，
# ocr_text 在使用处惰性导入，而非模块顶层导入。

# --------------------------------------------------------------------------- #
# 顶部条 / 中央区域（相对整张 result 页截图的 [left, top, right, bottom] 比例）
# --------------------------------------------------------------------------- #
_REGION = {
    # 中央金色「胜/败」大字
    "result": [0.46, 0.10, 0.54, 0.21],
    # 阵型（方圆阵 / 锥形阵）
    "formation_left": [0.35, 0.085, 0.44, 0.15],
    "formation_right": [0.56, 0.085, 0.66, 0.15],
    # 队伍总兵力 "当前/初始"（最左 / 最右）
    "team_hp_left": [0.03, 0.16, 0.16, 0.22],
    "team_hp_right": [0.84, 0.16, 0.97, 0.22],
    # 战损
    "team_loss_left": [0.23, 0.155, 0.35, 0.22],
    "team_loss_right": [0.65, 0.155, 0.80, 0.22],
    # 玩家名（最左 / 最右；中间是盟名，按 x 位置排除）
    "player_left": [0.03, 0.08, 0.18, 0.155],
    "player_right": [0.83, 0.08, 0.98, 0.155],
}

# 6 个武将卡片的横向中心（左队 3 个 + 右队 3 个），实测值。
_HERO_CENTERS = [0.108, 0.225, 0.355, 0.643, 0.766, 0.890]

# 卡片内部子区域（相对整图）：以卡片中心 cx 为基准的偏移。
_HERO_NAME_HALF_W = 0.040  # 武将名 "50曹操" 横向半宽（收窄以排除两侧血条数字）
_HERO_NAME_Y = (0.498, 0.552)
_HERO_HP_HALF_W = 0.055  # 血条 "0/11000"
_HERO_HP_Y = (0.553, 0.600)
_HERO_RED_HALF_W = 0.050  # 红度（红色刀形图标行）
_HERO_RED_Y = (0.470, 0.512)
# 战法名列（左对齐于卡片左侧）：相对卡片中心的 x 偏移与 3 行 y 范围。
_HERO_SKILL_X = (-0.068, 0.020)
_HERO_SKILL_Y = (0.620, 0.860)

# 战法列里需要剔除的非战法标签（缘分/影本等）与噪声。
_SKILL_DROP_TOKENS = ("缘分", "影本", "影分", "传承", "羁绊")


def _crop(image: np.ndarray, box: list[float]) -> np.ndarray:
    """按相对比例 [l, t, r, b] 从图像裁剪子区域。"""
    h, w = image.shape[:2]
    left = int(box[0] * w)
    top = int(box[1] * h)
    right = int(box[2] * w)
    bottom = int(box[3] * h)
    return image[top:bottom, left:right]


def _ocr_join(image: np.ndarray) -> str:
    """识别单行小区域文本（rec-only，跳过检测，速度快）。

    本函数用于已裁好、基本单行的区域（武将名/兵力/阵型/战损/玩家名/时间戳等）。
    多行或位置不定的区域（如战法列）请直接用 ocr_text。
    """
    from sanmou_report_analysis.utils.ocr import ocr_line

    return ocr_line(image)


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
    """识别左右阵型，如 ("方圆阵", "锥形阵")。只保留以「阵」结尾的中文。"""

    def _clean(t: str) -> str:
        # 阵型名固定为「2字+阵」（方圆阵/锥形阵/箕形阵…），排除盟名误入
        m = re.search(r"[\u4e00-\u9fff]{2}阵", t)
        return m.group(0) if m else t

    left = _clean(_ocr_join(_crop(image, _REGION["formation_left"])))
    right = _clean(_ocr_join(_crop(image, _REGION["formation_right"])))
    return left, right


def _normalize_player(text: str) -> str:
    """玩家名归一化：保留中文/字母/数字，去掉分隔符与空格（盟名已按区域排除）。"""
    return "".join(re.findall(r"[\u4e00-\u9fff0-9a-zA-Z]", text))


def parse_players(image: np.ndarray) -> tuple[str, str]:
    """识别左右玩家名（最左/最右，排除中间盟名）。"""
    left = _normalize_player(_ocr_join(_crop(image, _REGION["player_left"])))
    right = _normalize_player(_ocr_join(_crop(image, _REGION["player_right"])))
    return left, right


def parse_team_hp(image: np.ndarray) -> tuple[tuple | None, tuple | None]:
    """识别左右队伍总兵力 (当前, 初始)。"""
    left = _parse_hp_pair(_ocr_join(_crop(image, _REGION["team_hp_left"])))
    right = _parse_hp_pair(_ocr_join(_crop(image, _REGION["team_hp_right"])))
    return left, right


def _parse_loss(text: str) -> int | None:
    """从形如 "战损:14807" 的文本里解析出数字。"""
    digits = re.findall(r"\d+", text)
    return int(digits[0]) if digits else None


def parse_team_loss(image: np.ndarray) -> tuple[int | None, int | None]:
    """识别左右队伍战损。"""
    left = _parse_loss(_ocr_join(_crop(image, _REGION["team_loss_left"])))
    right = _parse_loss(_ocr_join(_crop(image, _REGION["team_loss_right"])))
    return left, right


def _count_red_by_color(region: np.ndarray) -> int:
    """颜色法数红度：橙色刀形图标的「段数」（暗背景下可靠）。"""
    import cv2

    if region.size == 0:
        return 0
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (8, 80, 80), (28, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 3), np.uint8))
    col = (mask > 0).sum(axis=0).astype(float)
    if col.max() <= 0:
        return 0
    col = np.convolve(col, np.ones(5) / 5, "same")
    on = col > col.max() * 0.4
    segs, prev = 0, False
    for v in on:
        if v and not prev:
            segs += 1
        prev = v
    return segs


def _count_red_stars(region: np.ndarray) -> int:
    """数红度（红色刀形图标数）。

    OCR 优先：刀形图标会被 OCR 识别为重复字符，字符数即红度（对 3~5 个准）。
    OCR 返回空时（常见于仅 2 个图标）回退到颜色段数法（暗背景下可靠）。
    """
    from sanmou_report_analysis.utils.ocr import ocr_text

    if region.size == 0:
        return 0
    text = "".join(o.text for o in ocr_text(region))
    glyphs = [c for c in text if not c.isspace()]
    if glyphs:
        return len(glyphs)
    return _count_red_by_color(region)


def _parse_hero_name(text: str) -> tuple[int | None, str]:
    """从 "50曹操" 解析 (等级, 名字)。

    等级固定为 50（满级），据此把开头的等级数字与混入的血条数字一并剥离，
    名字只保留中文字符，避免如 "0陆逊" 这类前导数字噪声。
    """
    digits = re.match(r"(\d{1,2})", text.strip())
    level = int(digits.group(1)) if digits else None
    name = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    return level, name


def _hero_box(cx: float, half_w: float, y0: float, y1: float) -> list[float]:
    """以卡片中心 cx 构造子区域 [l,t,r,b]（相对整图）。"""
    return [cx - half_w, y0, cx + half_w, y1]


def parse_hero_at(image: np.ndarray, cx: float) -> dict | None:
    """解析以 cx 为中心的单个武将卡片：名字/等级/兵力/红度/战法。

    空槽（未上阵/无名字）返回 None。
    """
    from sanmou_report_analysis.utils.ocr import ocr_text

    name_text = _ocr_join(_crop(image, _hero_box(cx, _HERO_NAME_HALF_W, *_HERO_NAME_Y)))
    level, name = _parse_hero_name(name_text)
    if not name:
        return None

    hp_pair = _parse_hp_pair(_ocr_join(_crop(image, _hero_box(cx, _HERO_HP_HALF_W, *_HERO_HP_Y))))
    final_hp, initial_hp = hp_pair if hp_pair else (None, None)

    # 红度：按颜色数红色刀形图标（不用 OCR）
    n_red = _count_red_stars(_crop(image, _hero_box(cx, _HERO_RED_HALF_W, *_HERO_RED_Y)))

    # 战法：OCR 卡片左侧的战法名列（一次），剔除「缘分/影本」标签与 ×次数/数字
    skill_box = [cx + _HERO_SKILL_X[0], _HERO_SKILL_Y[0], cx + _HERO_SKILL_X[1], _HERO_SKILL_Y[1]]
    skills: list[str] = []
    for r in sorted(ocr_text(_crop(image, skill_box)), key=lambda o: o.box.t):
        token = re.split(r"[×xX]", r.text)[0]
        token = re.sub(r"\d+", "", token).strip()
        token = "".join(re.findall(r"[\u4e00-\u9fff]", token))
        if not token or token in _SKILL_DROP_TOKENS:
            continue
        skills.append(token)

    return {
        "name": name,
        "level": level,
        "n_red": n_red,
        "final_hp": final_hp,
        "initial_hp": initial_hp,
        "skills": skills,
    }


def parse_team_heroes(image: np.ndarray, team: str) -> list[dict]:
    """解析某一方（left/right）的最多 3 个武将。"""
    centers = _HERO_CENTERS[:3] if team == "left" else _HERO_CENTERS[3:]
    heroes = []
    for cx in centers:
        info = parse_hero_at(image, cx)
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
    player_left, player_right = parse_players(image)

    return {
        "result": result,
        "formation": {"left": formation_left, "right": formation_right},
        "teams": {
            "left": {
                "player": player_left,
                "hp": left_hp,
                "loss": loss_left,
                "heroes": parse_team_heroes(image, "left"),
            },
            "right": {
                "player": player_right,
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
