"""基础校验测试。"""

from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.normalization import normalize_daily_bar, normalize_fund_nav
from backend.app.services.quality import quality_from_issues, should_persist
from backend.app.services.validation import validate_daily_bar, validate_fund_nav


class DailyBarValidationTest(unittest.TestCase):
    def test_valid_row_has_no_issues(self):
        row = normalize_daily_bar(
            {
                "日期": "2024-01-02",
                "开盘": 10.0,
                "最高": 10.5,
                "最低": 9.8,
                "收盘": 10.2,
                "成交量": 1000,
                "成交额": 10000,
            }
        )
        issues = validate_daily_bar(row)
        self.assertEqual([], issues)
        self.assertEqual("normal", quality_from_issues(issues))
        self.assertTrue(should_persist(issues))

    def test_turnover_may_be_empty_for_index(self):
        row = normalize_daily_bar(
            {
                "date": "2024-01-02",
                "open": 3000,
                "high": 3010,
                "low": 2990,
                "close": 3005,
                "volume": 1000,
                "amount": None,
            }
        )
        issues = validate_daily_bar(row)
        self.assertEqual([], issues)
        self.assertIsNone(row["turnover"])

    def test_ohlc_relation_error_is_non_blocking(self):
        row = normalize_daily_bar(
            {
                "date": "2024-01-02",
                "open": 10.0,
                "high": 9.0,
                "low": 11.0,
                "close": 10.2,
                "volume": 1000,
            }
        )
        issues = validate_daily_bar(row)
        self.assertTrue(issues)
        self.assertFalse(any(i.blocking for i in issues))
        self.assertEqual("source_anomaly", quality_from_issues(issues))
        self.assertTrue(should_persist(issues))

    def test_missing_price_is_blocking(self):
        row = normalize_daily_bar({"date": "2024-01-02", "open": 10.0, "high": 10.5, "low": 9.8, "volume": 1000})
        issues = validate_daily_bar(row)
        self.assertTrue(any(i.blocking for i in issues))
        self.assertFalse(should_persist(issues))

    def test_invalid_date_is_blocking(self):
        row = normalize_daily_bar(
            {"date": "not-a-date", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}
        )
        issues = validate_daily_bar(row)
        self.assertTrue(any(i.field == "trade_date" and i.blocking for i in issues))

    def test_negative_volume_is_blocking(self):
        row = normalize_daily_bar(
            {"date": "2024-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": -5}
        )
        issues = validate_daily_bar(row)
        self.assertTrue(any(i.code == "NEGATIVE_VOLUME" and i.blocking for i in issues))


class FundNavValidationTest(unittest.TestCase):
    def test_valid_nav(self):
        row = normalize_fund_nav({"净值日期": "2024-01-02", "单位净值": 1.5, "累计净值": 1.8})
        self.assertEqual([], validate_fund_nav(row))

    def test_accumulated_nav_may_be_missing(self):
        row = normalize_fund_nav({"nav_date": "2024-01-02", "unit_nav": 1.5})
        issues = validate_fund_nav(row)
        self.assertEqual([], issues)

    def test_non_positive_unit_nav_is_blocking(self):
        row = normalize_fund_nav({"nav_date": "2024-01-02", "unit_nav": 0})
        issues = validate_fund_nav(row)
        self.assertTrue(any(i.blocking for i in issues))


if __name__ == "__main__":
    unittest.main()
