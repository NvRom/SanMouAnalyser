import unittest

from sanmou_report_analysis.utils.battle_summary import (
    _infer_result_from_hp,
    _parse_hero_name,
    _parse_hp_pair,
    _parse_loss,
)


class BattleSummaryParsingTest(unittest.TestCase):
    def test_parse_hp_pair(self):
        self.assertEqual(_parse_hp_pair("8845/40000"), (8845, 40000))
        self.assertEqual(_parse_hp_pair("28435/30000"), (28435, 30000))
        self.assertEqual(_parse_hp_pair("0/21856"), (0, 21856))
        # OCR 常见误识别 O -> 0、全角斜杠
        self.assertEqual(_parse_hp_pair("O/3OOOO"), (0, 30000))
        self.assertEqual(_parse_hp_pair("16360／30000"), (16360, 30000))
        self.assertIsNone(_parse_hp_pair("abc"))

    def test_parse_loss(self):
        self.assertEqual(_parse_loss("战损:891"), 891)
        self.assertEqual(_parse_loss("9035:战损"), 9035)
        self.assertIsNone(_parse_loss("战损"))

    def test_parse_hero_name(self):
        self.assertEqual(_parse_hero_name("50典韦"), (50, "典韦"))
        self.assertEqual(_parse_hero_name("50 曹操"), (50, "曹操"))
        self.assertEqual(_parse_hero_name("太史慈"), (None, "太史慈"))

    def test_infer_result_from_hp(self):
        # 右方全灭 -> 我方（左）胜
        self.assertEqual(_infer_result_from_hp((28435, 30000), (0, 21856)), "胜")
        # 左方全灭 -> 我方败
        self.assertEqual(_infer_result_from_hp((0, 20459), (8544, 19728)), "败")
        # 双方都有兵力 -> 无法判定
        self.assertEqual(_infer_result_from_hp((100, 200), (100, 200)), "未知")


if __name__ == "__main__":
    unittest.main()
