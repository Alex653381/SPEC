"""按代码新增真实资产的校验测试。"""

from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.asset_registration import normalize_index_code, register_asset


class AssetRegistrationValidationTest(unittest.TestCase):
    def test_index_code_normalization(self):
        self.assertEqual("sh000688", normalize_index_code("000688"))
        self.assertEqual("sz399001", normalize_index_code("399001"))
        self.assertEqual("sh000001", normalize_index_code("sh000001"))

    def test_invalid_stock_code_rejected_before_network(self):
        with self.assertRaises(ValueError):
            register_asset("stock", "bad", None, None, date(2026, 10, 1), date(2026, 10, 30))

    def test_invalid_etf_code_rejected_before_network(self):
        with self.assertRaises(ValueError):
            register_asset("etf", "abc", None, None, date(2026, 10, 1), date(2026, 10, 30))

    def test_unsupported_asset_type_rejected(self):
        with self.assertRaises(ValueError):
            register_asset("crypto", "btc", None, None, date(2026, 10, 1), date(2026, 10, 30))

    def test_invalid_index_code_rejected_before_network(self):
        with self.assertRaises(ValueError):
            register_asset("index", "bad", None, None, date(2026, 10, 1), date(2026, 10, 30))

    def test_invalid_fund_code_rejected_before_network(self):
        with self.assertRaises(ValueError):
            register_asset("fund", "abc", None, None, date(2026, 10, 1), date(2026, 10, 30))


if __name__ == "__main__":
    unittest.main()
