"""真实接口验证摘要逻辑的离线测试。"""

from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.live_validation import (
    recent_window,
    summarize_daily_rows,
    summarize_fund_rows,
)


class LiveValidationTest(unittest.TestCase):
    def test_recent_window(self):
        start, end = recent_window(days=20, today=date(2026, 10, 31))
        self.assertEqual(date(2026, 10, 11), start)
        self.assertEqual(date(2026, 10, 31), end)

    def test_summarize_daily_rows(self):
        rows = [
            {"date": "2024-01-02", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
            {"date": "2024-01-03", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
            {"date": "2024-01-03", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
            {"date": "bad-date", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
            {"date": "2024-01-04", "open": 10, "high": 9.0, "low": 11.0, "close": 10.2, "volume": 1000},
            {"date": "2024-01-05", "open": float("nan"), "high": 10, "low": 9, "close": 10, "volume": 1000},
        ]
        summary = summarize_daily_rows(rows)
        self.assertEqual(6, summary["rows"])
        self.assertEqual(1, summary["invalid_dates"])
        self.assertEqual(1, summary["duplicate_dates"])
        self.assertEqual(1, summary["ohlc_violations"])
        self.assertGreaterEqual(summary["non_finite_values"], 1)
        self.assertEqual("2024-01-02", summary["date_min"])
        self.assertEqual("2024-01-05", summary["date_max"])

    def test_summarize_fund_rows_reports_weekend_without_removing(self):
        rows = [
            {"净值日期": "2024-01-02", "单位净值": 1.5, "累计净值": 1.8},
            {"净值日期": "2024-01-06", "单位净值": 1.52, "累计净值": 1.82},
        ]
        summary = summarize_fund_rows(rows, calendar={date(2024, 1, 2), date(2024, 1, 3)})
        self.assertEqual(["2024-01-06"], summary["weekend_dates_reported"])
        self.assertEqual(["2024-01-06"], summary["calendar_mismatches_reported"])


if __name__ == "__main__":
    unittest.main()
