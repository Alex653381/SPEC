"""数据源适配器离线 Mock 测试。所有样本均为合成数据。"""

from __future__ import annotations

import unittest
import math
from datetime import date

from backend.app.providers.base import NetworkError
from backend.app.providers.eastmoney import EastmoneyFundAdapter
from backend.app.providers.sina import SinaETFAdapter, SinaIndexAdapter, SinaStockAdapter
from backend.app.schemas.records import DailyBarRecord, FundNavRecord
from backend.app.services.calendar import partition_fund_nav
from backend.app.services.merge import merge_daily_bars


STOCK_ROW = {
    "date": "2024-01-02",
    "open": 10.0,
    "high": 10.5,
    "low": 9.8,
    "close": 10.2,
    "volume": 1000,
    "amount": 10200,
}


class AdapterContractTest(unittest.TestCase):
    def test_adapters_declare_capabilities(self):
        stock = SinaStockAdapter(lambda *_: [])
        index = SinaIndexAdapter(lambda *_: [])
        etf = SinaETFAdapter(lambda *_: [])
        fund = EastmoneyFundAdapter(lambda *_: [])
        self.assertEqual("stock", stock.asset_type)
        self.assertTrue(stock.supports_date_range)
        self.assertFalse(index.supports_date_range)
        self.assertFalse(etf.supports_date_range)
        self.assertFalse(fund.supports_date_range)

    def test_stock_mapping_and_metadata(self):
        adapter = SinaStockAdapter(lambda *_: [STOCK_ROW])
        result = adapter.fetch_history("asset-stock-1", start=date(2024, 1, 1), end=date(2024, 1, 31))
        self.assertFalse(result.empty)
        self.assertEqual([], result.errors)
        self.assertEqual(1, len(result.records))
        record = result.records[0]
        self.assertIsInstance(record, DailyBarRecord)
        self.assertEqual("sina", record.provider)
        self.assertEqual("qfq", record.adjustment_mode)
        self.assertEqual(10200.0, record.turnover)
        self.assertIsNotNone(record.fetched_at)

    def test_stock_prefers_amount_over_turnover_column(self):
        row = {**STOCK_ROW, "turnover": 0.0065}
        adapter = SinaStockAdapter(lambda *_: [row])
        record = adapter.fetch_history("asset-stock-1").records[0]
        self.assertEqual(10200.0, record.turnover)

    def test_index_turnover_is_empty(self):
        adapter = SinaIndexAdapter(lambda *_: [{"date": "2024-01-02", "open": 3000, "high": 3010, "low": 2990, "close": 3005, "volume": 1000}])
        record = adapter.fetch_history("asset-index-1").records[0]
        self.assertIsNone(record.turnover)
        self.assertEqual("none", record.adjustment_mode)

    def test_etf_maps_amount_to_turnover(self):
        adapter = SinaETFAdapter(lambda *_: [STOCK_ROW])
        record = adapter.fetch_history("asset-etf-1").records[0]
        self.assertEqual(10200.0, record.turnover)

    def test_non_finite_turnover_is_dropped_and_marked(self):
        row = dict(STOCK_ROW)
        row["amount"] = float("nan")
        adapter = SinaStockAdapter(lambda *_: [row])
        result = adapter.fetch_history("asset-1")
        record = result.records[0]
        self.assertIsNone(record.turnover)
        self.assertEqual("source_anomaly", record.quality_status)

    def test_non_range_adapter_passes_none_dates_to_fetcher(self):
        captured = {}

        def fetcher(asset_id, start, end):
            captured.update(asset_id=asset_id, start=start, end=end)
            return [{"date": "2024-01-02", "open": 3000, "high": 3010, "low": 2990, "close": 3005, "volume": 1000}]

        adapter = SinaIndexAdapter(fetcher)
        adapter.fetch_history("asset-index-1", start=date(2024, 1, 1), end=date(2024, 1, 31))
        self.assertIsNone(captured["start"])
        self.assertIsNone(captured["end"])

    def test_fund_mapping_has_no_ohlc(self):
        adapter = EastmoneyFundAdapter(
            lambda *_: [{"净值日期": "2024-01-02", "单位净值": 1.5, "累计净值": 1.8, "日增长率": 0.5}]
        )
        result = adapter.fetch_history("asset-fund-1")
        record = result.records[0]
        self.assertIsInstance(record, FundNavRecord)
        self.assertEqual(1.5, record.unit_nav)
        self.assertEqual(1.8, record.accumulated_nav)
        self.assertFalse(hasattr(record, "open"))
        self.assertFalse(hasattr(record, "volume"))


class AdapterErrorTest(unittest.TestCase):
    def test_empty_response(self):
        adapter = SinaStockAdapter(lambda *_: [])
        result = adapter.fetch_history("asset-1")
        self.assertTrue(result.empty)
        self.assertEqual([], result.records)

    def test_network_error_is_wrapped(self):
        def fail(*_):
            raise ConnectionError("boom")

        adapter = SinaStockAdapter(fail)
        with self.assertRaises(NetworkError):
            adapter.fetch_history("asset-1")

    def test_missing_required_field_is_blocking(self):
        row = dict(STOCK_ROW)
        row.pop("close")
        adapter = SinaStockAdapter(lambda *_: [row])
        result = adapter.fetch_history("asset-1")
        self.assertEqual([], result.records)
        self.assertTrue(any(e.code == "VALIDATION_BLOCKING" for e in result.errors))

    def test_unparseable_date_is_blocking(self):
        row = dict(STOCK_ROW)
        row["date"] = "not-a-date"
        adapter = SinaStockAdapter(lambda *_: [row])
        result = adapter.fetch_history("asset-1")
        self.assertTrue(any(e.code == "VALIDATION_BLOCKING" for e in result.errors))

    def test_bad_numeric_format_is_blocking(self):
        row = dict(STOCK_ROW)
        row["open"] = "abc"
        adapter = SinaStockAdapter(lambda *_: [row])
        result = adapter.fetch_history("asset-1")
        self.assertTrue(any(e.code == "VALIDATION_BLOCKING" for e in result.errors))

    def test_ohlc_anomaly_is_kept_and_marked(self):
        row = dict(STOCK_ROW)
        row["high"] = 9.0
        adapter = SinaStockAdapter(lambda *_: [row])
        result = adapter.fetch_history("asset-1")
        self.assertEqual(1, len(result.records))
        self.assertEqual("source_anomaly", result.records[0].quality_status)

    def test_duplicate_date_is_dropped_from_batch(self):
        adapter = SinaStockAdapter(lambda *_: [STOCK_ROW, dict(STOCK_ROW)])
        result = adapter.fetch_history("asset-1")
        self.assertEqual(1, len(result.records))
        self.assertTrue(any(e.code == "DUPLICATE_DATE" for e in result.errors))

    def test_out_of_range_rows_are_filtered(self):
        rows = [STOCK_ROW, {**STOCK_ROW, "date": "2024-03-01"}]
        adapter = SinaStockAdapter(lambda *_: rows)
        result = adapter.fetch_history("asset-1", start=date(2024, 1, 1), end=date(2024, 1, 31))
        self.assertEqual(1, len(result.records))
        self.assertTrue(any(e.code == "OUT_OF_RANGE" for e in result.errors))

    def test_changed_field_names_are_reported(self):
        adapter = SinaStockAdapter(lambda *_: [{"d": "2024-01-02", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}])
        result = adapter.fetch_history("asset-1")
        self.assertEqual([], result.records)
        self.assertTrue(result.errors)


class AdapterMergeTest(unittest.TestCase):
    def test_repeated_import_does_not_duplicate(self):
        adapter = SinaStockAdapter(lambda *_: [STOCK_ROW])
        first = adapter.fetch_history("asset-1").records
        second = adapter.fetch_history("asset-1").records
        merged, conflicts = merge_daily_bars(first, second)
        self.assertEqual(1, len(merged))
        self.assertEqual([], conflicts)

    def test_anomaly_does_not_overwrite_valid(self):
        adapter = SinaStockAdapter(lambda *_: [STOCK_ROW])
        existing = adapter.fetch_history("asset-1").records
        bad = [{**STOCK_ROW, "close": 999.0}]
        incoming = SinaStockAdapter(lambda *_: bad).fetch_history("asset-1").records
        merged, conflicts = merge_daily_bars(existing, incoming, preserve_existing=True)
        self.assertEqual(10.2, merged[0].close)
        self.assertEqual(1, len(conflicts))


class FundPlaceholderTest(unittest.TestCase):
    def test_weekend_placeholder_is_isolated_not_deleted_by_guess(self):
        adapter = EastmoneyFundAdapter(
            lambda *_: [
                {"净值日期": "2024-01-02", "单位净值": 1.5},
                {"净值日期": "2024-01-03", "单位净值": 1.52},
                {"净值日期": "2024-01-06", "单位净值": 1.52},
            ]
        )
        records = adapter.fetch_history("asset-fund-1").records
        valid, placeholders = partition_fund_nav(records, {date(2024, 1, 6)})
        self.assertEqual(2, len(valid))
        self.assertEqual([date(2024, 1, 6)], [r.nav_date for r in placeholders])


if __name__ == "__main__":
    unittest.main()
