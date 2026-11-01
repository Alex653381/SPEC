"""首选数据源适配器准备的离线测试。"""

from __future__ import annotations

import unittest

from backend.app.providers.eastmoney import EastmoneyETFAdapter
from backend.app.providers.fund_lsjz import LsjzFundAdapter, collect_pages, map_lsjz_item
from backend.app.providers.tencent import TencentIndexAdapter


class TencentIndexReadinessTest(unittest.TestCase):
    def test_amount_is_volume_not_turnover(self):
        adapter = TencentIndexAdapter(
            lambda *_: [{"date": "2024-01-02", "open": 3000, "high": 3010, "low": 2990, "close": 3005, "amount": 1234}]
        )
        result = adapter.fetch_history("index-1", start=None, end=None)
        record = result.records[0]
        self.assertEqual(1234.0, record.volume)
        self.assertIsNone(record.turnover)
        self.assertEqual("none", record.adjustment_mode)
        self.assertTrue(adapter.supports_date_range)


class EastmoneyETFReadinessTest(unittest.TestCase):
    def test_em_field_mapping(self):
        adapter = EastmoneyETFAdapter(
            lambda *_: [
                {
                    "日期": "2024-01-02",
                    "开盘": 4.0,
                    "收盘": 4.05,
                    "最高": 4.08,
                    "最低": 3.98,
                    "成交量": 5000,
                    "成交额": 20250,
                }
            ]
        )
        record = adapter.fetch_history("etf-1").records[0]
        self.assertEqual(4.0, record.open)
        self.assertEqual(4.05, record.close)
        self.assertEqual(5000.0, record.volume)
        self.assertEqual(20250.0, record.turnover)
        self.assertEqual("none", record.adjustment_mode)
        self.assertTrue(adapter.supports_date_range)


class LsjzFundReadinessTest(unittest.TestCase):
    def test_lsjz_field_mapping(self):
        mapped = map_lsjz_item({"FSRQ": "2024-01-02", "DWJZ": 1.5, "LJJZ": 1.8})
        self.assertEqual("2024-01-02", mapped["nav_date"])
        self.assertEqual(1.5, mapped["unit_nav"])
        self.assertEqual(1.8, mapped["accumulated_nav"])

    def test_adapter_builds_fund_nav(self):
        adapter = LsjzFundAdapter(
            lambda *_: [{"FSRQ": "2024-01-02", "DWJZ": 1.5, "LJJZ": 1.8}]
        )
        result = adapter.fetch_history("fund-1")
        self.assertTrue(adapter.supports_date_range)
        self.assertEqual(1.5, result.records[0].unit_nav)

    def test_collect_pages_stops_on_empty_page(self):
        calls = []

        def load_page(page):
            calls.append(page)
            return [] if page >= 2 else [{"FSRQ": "2024-01-02"}]

        rows = collect_pages(load_page, page_size=1)
        self.assertEqual(1, len(rows))
        self.assertEqual([1, 2], calls)

    def test_collect_pages_deduplicates_by_date(self):
        def load_page(page):
            return [{"FSRQ": "2024-01-02"}, {"FSRQ": "2024-01-02"}, {"FSRQ": "2024-01-03"}]

        rows = collect_pages(load_page, page_size=20)
        self.assertEqual(2, len(rows))

    def test_collect_pages_respects_max_pages(self):
        def load_page(page):
            return [{"FSRQ": f"2024-01-{page:02d}"}]

        rows = collect_pages(load_page, page_size=1, max_pages=3)
        self.assertEqual(3, len(rows))


if __name__ == "__main__":
    unittest.main()
