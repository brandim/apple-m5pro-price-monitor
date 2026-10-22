import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import price_check
from price_check import URL, verify


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.summary = (
            "14 英寸 MacBook Pro M5 芯片 10 核 CPU 10 核 GPU 深空黑色 "
            "标准显示屏 24GB 统一内存 1TB SSD 70W USB-C 电源适配器 "
            "带触控 ID 的中文（拼音）键盘。一次性付款 RMB 17,499"
        )
        self.dom = {
            "url": URL,
            "bodyText": self.summary,
            "summary": [{"text": self.summary, "priceNodes": [{"text": "RMB 17,499", "html": "<span class='as-pricepoint-fullprice'>RMB 17,499</span>"}]}],
            "serverSelections": {
                "SCREEN_SIZE": "14inch", "CHASSIS_COLOR": "spaceblack",
                "DISPLAY_FINISH": "standard", "MEMORY": {"dimensionValue": "24gb"},
                "STORAGE": {"dimensionValue": "1tb"},
                "POWER_ADAPTER": {"dimensionValue": "70w"},
                "KEYBOARD_LANGUAGE": {"dimensionValue": "chn"},
                "PROCESSOR": {"dimensionChip": "m5", "cpuCoreCount": "10", "gpuCoreCount": "10"},
                "LOGIC_PRO": {"dimensionValue": "none"},
                "FINAL_CUT_PRO": {"dimensionValue": "none"},
            },
            "choices": [
                {"label": label, "checked": True, "ariaChecked": None,
                 "ariaSelected": None, "selectedOption": None}
                for label in ("24GB 统一内存", "1TB SSD", "70W USB-C 电源适配器", "中文（拼音）键盘")
            ],
        }
        self.keyboard = {"selected": True}

    def test_accepts_only_complete_summary(self):
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertIsNone(error)
        self.assertTrue(all(checks.values()))
        self.assertEqual(price, 17499)

    def test_rejects_missing_selected_keyboard(self):
        checks, price, error = verify(self.dom, {"selected": False})
        self.assertFalse(checks["selected_keyboard"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_installment_as_total(self):
        self.dom["summary"][0]["text"] = self.summary.replace("一次性付款 RMB 17,499", "分期付款 RMB 999")
        self.dom["summary"][0]["priceNodes"] = []
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["purchase_summary_with_fullprice"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_starting_price(self):
        self.dom["summary"][0]["priceNodes"] = [{"text": "RMB 17,499", "html": "<span>RMB 17,499</span>",
                                                     "parentText": "RMB 17,499 起", "parentHtml": "<div>RMB 17,499 起</div>"}]
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["unique_one_time_total"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_wrong_adapter_even_with_price(self):
        self.dom["serverSelections"]["POWER_ADAPTER"]["dimensionValue"] = "96w"
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["apple_selected_state"]["POWER_ADAPTER"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_m5_pro_even_with_a_price(self):
        self.dom["serverSelections"]["PROCESSOR"]["dimensionChip"] = "m5pro"
        self.dom["summary"][0]["text"] = self.summary.replace("M5 芯片", "M5 Pro 芯片")
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["apple_selected_state"]["PROCESSOR"])
        self.assertFalse(checks["summary_matches_configuration"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_price_outside_matching_configuration_summary(self):
        self.dom["summary"][0]["text"] = self.summary.replace("70W USB-C", "96W USB-C")
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["summary_matches_configuration"])
        self.assertFalse(checks["purchase_summary_with_fullprice"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_rejects_missing_touch_id_evidence(self):
        self.dom["bodyText"] = self.summary.replace("带触控 ID 的", "")
        checks, price, error = verify(self.dom, self.keyboard)
        self.assertFalse(checks["keyboard_has_touch_id"])
        self.assertIsNone(price)
        self.assertIsNotNone(error)

    def test_history_ignores_other_product(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "history.jsonl"
            history.write_text(
                '{"verified":true,"url":"https://example.com/m5-pro","price_cny":19999}\n'
                + '{"verified":true,"url":"' + URL + '","price_cny":17499}\n'
                + '{"verified":true,"url":"https://example.com/m5-pro","price_cny":18999}\n',
                encoding="utf-8",
            )
            with patch.object(price_check, "HISTORY", history):
                self.assertEqual(price_check.history_previous()["price_cny"], 17499)


if __name__ == "__main__":
    unittest.main()
