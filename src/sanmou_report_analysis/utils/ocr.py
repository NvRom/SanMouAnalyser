# Author: Mian Qin
# Date Created: 2025/1/3
#
# 适配 PaddleOCR 3.x（3.4+）：
# - 构造参数变更：移除 `use_gpu` / `show_log`，`use_angle_cls` → `use_textline_orientation`；
#   GPU/CPU 由所装的 paddlepaddle 版本与 `device` 决定（默认自动选择）。
# - `enable_mkldnn=False`：规避部分 paddlepaddle 构建在 oneDNN 下的推理报错
#   （NotImplementedError: ConvertPirAttribute2RuntimeAttribute）。
# - 返回结构变更：`.predict()` 返回 `OCRResult` 字典列表，
#   含 `rec_texts` 与 `rec_boxes`（轴对齐 [l, t, r, b]）。

import logging
import os

# 跳过模型源连通性检查（避免每次启动等待联网探测）。
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from paddleocr import PaddleOCR

from sanmou_report_analysis.utils.data_structure import OCRResult

# 仅 CPU 推理。
_DEVICE = "cpu"

# 当前 paddle 版本在 CPU 下开启 mkldnn 会触发 ConvertPirAttribute2RuntimeAttribute
# 崩溃，故关闭 oneDNN。
_USE_MKLDNN = False

# 关闭用不到的文档方向/扭曲矫正模型（少加载两个模型、启动更快），仅保留检测+识别。
# 显式使用 **mobile 轻量模型**：比默认的 PP-OCRv5_server 模型快 5~10 倍，
# 对游戏内清晰文字精度几乎无损（实测小区域 OCR 0.98s→0.20s）。
_COMMON_KWARGS = {
    "use_textline_orientation": False,
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "enable_mkldnn": _USE_MKLDNN,
    "device": _DEVICE,
}

OCRer = PaddleOCR(
    lang="ch",
    text_detection_model_name="PP-OCRv5_mobile_det",
    text_recognition_model_name="PP-OCRv5_mobile_rec",
    **_COMMON_KWARGS,
)
# 数字识别用英文 mobile 识别模型（中文 det 仍可复用，但英文 rec 对纯数字更快更准）。
OCRer_number = PaddleOCR(
    lang="en",
    text_detection_model_name="PP-OCRv5_mobile_det",
    text_recognition_model_name="en_PP-OCRv5_mobile_rec",
    **_COMMON_KWARGS,
)
logging.getLogger("ppocr").setLevel(logging.ERROR)

# 仅识别（rec-only）模型：跳过最贵的「文字检测」步骤。对已裁好的单行小区域，
# 实测 0.191s → 0.034s（快约 5.6 倍）且结果一致。延迟初始化，按需加载。
_RecOnly = None


def _get_rec_only():
    """构造仅识别（rec-only）模型（CPU），延迟初始化。"""
    global _RecOnly
    if _RecOnly is None:
        from paddleocr import TextRecognition

        _RecOnly = TextRecognition(model_name="PP-OCRv5_mobile_rec", device=_DEVICE)
    return _RecOnly


def ocr_line(image) -> str:
    """仅识别单行文本（跳过检测，速度快）。

    适用于「已知位置、已裁好、基本只含一行字」的小区域（武将名、兵力、阵型、
    战损、玩家名、技能名等）。返回识别到的文本（去空白）；失败返回空串。
    多行/位置不定的区域请用 ocr_text。
    """
    if image is None or getattr(image, "size", 0) == 0:
        return ""
    try:
        out = _get_rec_only().predict(image)
    except Exception:
        return ""
    if not out:
        return ""
    first = out[0]
    text = first.get("rec_text", "") if hasattr(first, "get") else ""
    return text.strip()


def _parse_ocr_output(raw) -> list[OCRResult]:
    """把 PaddleOCR 输出解析成统一的 OCRResult 列表，兼容 3.x 与旧版格式。"""
    ocr_results: list[OCRResult] = []
    if not raw:
        return ocr_results

    first = raw[0]

    # PaddleOCR 3.x：first 是 OCRResult 字典，含 rec_texts / rec_boxes
    if hasattr(first, "keys") and "rec_texts" in first:
        texts = first.get("rec_texts", [])
        boxes = first.get("rec_boxes", None)
        polys = first.get("rec_polys", None)
        for i, text in enumerate(texts):
            if boxes is not None and i < len(boxes):
                left, top, right, bottom = (int(v) for v in boxes[i][:4])
            elif polys is not None and i < len(polys):
                poly = polys[i]
                xs = [int(p[0]) for p in poly]
                ys = [int(p[1]) for p in poly]
                left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
            else:
                continue
            ocr_result = OCRResult((left, top, right, bottom), text)
            ocr_result.box.expand(5, 5)
            ocr_results.append(ocr_result)
        return ocr_results

    # 旧版（2.x）：first 是 [[box, (text, score)], ...]
    for result in first:
        corners = result[0]
        left = int(corners[0][0])
        right = int(corners[1][0])
        top = int(corners[0][1])
        bottom = int(corners[2][1])
        text = result[1][0]
        ocr_result = OCRResult((left, top, right, bottom), text)
        ocr_result.box.expand(5, 5)
        ocr_results.append(ocr_result)
    return ocr_results


def ocr_text(image, save=False) -> list[OCRResult]:
    return _parse_ocr_output(OCRer.predict(image))


def ocr_number(image, save=False) -> list[OCRResult]:
    return _parse_ocr_output(OCRer_number.predict(image))
