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

# 关闭用不到的文档方向/扭曲矫正模型（少加载两个模型、启动更快），仅保留检测+识别。
_OCR_KWARGS = {
    "use_textline_orientation": False,
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "enable_mkldnn": False,
}

OCRer = PaddleOCR(lang="ch", **_OCR_KWARGS)
OCRer_number = PaddleOCR(lang="en", **_OCR_KWARGS)
logging.getLogger("ppocr").setLevel(logging.ERROR)


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
