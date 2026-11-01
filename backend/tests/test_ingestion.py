"""采集服务端到端测试。全部使用临时数据库和 Mock fetcher。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest import mock

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.core.config import AppSettings
from backend.app.db import repository
from backend.app.db.database import connect, init_db
from backend.app.schemas.records import AssetRecord
from backend.app.services import ingestion
from backend.app.services.ingestion import (
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    ingest,
)


STOCK_ROW = {
    "date": "2024-01-02",
    "open": 10.0,
    "high": 10.5,
    "low": 9.8,
    "close": 10.2,
    "volume": 1000,
    "amount": 10200,
}


def _asset(asset_id, asset_type, symbol):
    return AssetRecord(
        id=asset_id,
        symbol=symbol,
        name=f"SYN-{asset_type}",
        asset_type=asset_type,
        market="SZ" if asset_type == "stock" else "SH",
        provider="synthetic",
        provider_symbol=symbol,
        price_semantics="unit_nav" if asset_type == "open_fund" else "close",
        volume_unit=None if asset_type == "open_fund" else "shares",
        adjustment_mode="qfq" if asset_type == "stock" else None,
    )


class IngestionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "ingest.db")
        self.conn = init_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _seed_asset(self, asset_id, asset_type, symbol):
        with self.conn:
            repository.insert_asset(self.conn, _asset(asset_id, asset_type, symbol))

    def test_stock_ingest_success(self):
        self._seed_asset("stock-1", "stock", "000001")
        result = ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW])
        self.assertEqual(STATUS_SUCCESS, result.status)
        self.assertEqual(1, result.fetched_rows)
        self.assertEqual(1, result.written_rows)

    def test_index_ingest_with_no_turnover(self):
        self._seed_asset("index-1", "index", "000001")
        row = {"date": "2024-01-02", "open": 3000, "high": 3010, "low": 2990, "close": 3005, "volume": 1000}
        result = ingest(self.conn, "index-1", lambda *_: [row])
        self.assertEqual(STATUS_SUCCESS, result.status)
        stored = repository.query_daily_bars(self.conn, "index-1")
        self.assertIsNone(stored[0].turnover)

    def test_fund_ingest_keeps_non_trading_nav_when_no_rule(self):
        self._seed_asset("fund-1", "open_fund", "110022")
        calendar = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)}
        fetcher = lambda *_: [
            {"净值日期": "2024-01-02", "单位净值": 1.5},
            {"净值日期": "2024-01-03", "单位净值": 1.52},
            {"净值日期": "2024-01-06", "单位净值": 1.52},
        ]
        result = ingest(self.conn, "fund-1", fetcher, calendar=calendar)
        self.assertEqual(STATUS_SUCCESS, result.status)
        self.assertEqual(3, result.written_rows)
        self.assertEqual(0, result.skipped_rows)

    def test_fund_without_calendar_imports_valid_nav(self):
        self._seed_asset("fund-1", "open_fund", "110022")
        result = ingest(self.conn, "fund-1", lambda *_: [{"净值日期": "2024-01-02", "单位净值": 1.5}])
        self.assertEqual(STATUS_SUCCESS, result.status)
        self.assertEqual(1, len(repository.query_fund_navs(self.conn, "fund-1")))

    def test_repeated_ingest_is_idempotent(self):
        self._seed_asset("stock-1", "stock", "000001")
        first = ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW])
        second = ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW])
        self.assertEqual(1, first.written_rows)
        self.assertEqual(0, second.written_rows)
        self.assertEqual(1, len(repository.query_daily_bars(self.conn, "stock-1")))

    def test_empty_result(self):
        self._seed_asset("stock-1", "stock", "000001")
        result = ingest(self.conn, "stock-1", lambda *_: [])
        self.assertEqual(STATUS_EMPTY, result.status)
        self.assertEqual(0, result.written_rows)

    def test_network_failure(self):
        self._seed_asset("stock-1", "stock", "000001")
        result = ingest(self.conn, "stock-1", lambda *_: (_ for _ in ()).throw(ConnectionError("boom")))
        self.assertEqual(STATUS_FAILED, result.status)

    def test_invalid_response_fails(self):
        self._seed_asset("stock-1", "stock", "000001")
        result = ingest(self.conn, "stock-1", lambda *_: {"not": "a list"})
        self.assertEqual(STATUS_FAILED, result.status)

    def test_partial_valid_and_invalid_rows(self):
        self._seed_asset("stock-1", "stock", "000001")
        bad = dict(STOCK_ROW)
        bad.pop("close")
        result = ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW, bad])
        self.assertEqual(STATUS_PARTIAL, result.status)
        self.assertEqual(1, result.written_rows)
        self.assertEqual(1, result.skipped_rows)

    def test_incoming_does_not_overwrite_existing(self):
        self._seed_asset("stock-1", "stock", "000001")
        ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW])
        changed = {**STOCK_ROW, "close": 99.0}
        result = ingest(self.conn, "stock-1", lambda *_: [changed])
        self.assertEqual(0, result.written_rows)
        self.assertEqual(10.2, repository.query_daily_bars(self.conn, "stock-1")[0].close)

    def test_missing_asset_fails(self):
        result = ingest(self.conn, "missing", lambda *_: [STOCK_ROW])
        self.assertEqual(STATUS_FAILED, result.status)

    def test_transaction_rollback_on_write_error(self):
        self._seed_asset("stock-1", "stock", "000001")
        with mock.patch(
            "backend.app.services.ingestion.repository.insert_daily_bars",
            side_effect=sqlite3.IntegrityError("boom"),
        ):
            result = ingest(self.conn, "stock-1", lambda *_: [STOCK_ROW])
        self.assertEqual(STATUS_FAILED, result.status)
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-1"))

    def test_non_finite_values_are_not_written(self):
        self._seed_asset("stock-1", "stock", "000001")
        nan_price = {**STOCK_ROW, "open": float("nan")}
        nan_amount = {**STOCK_ROW, "amount": float("inf")}
        result = ingest(self.conn, "stock-1", lambda *_: [nan_price, nan_amount])
        self.assertEqual(STATUS_PARTIAL, result.status)
        stored = repository.query_daily_bars(self.conn, "stock-1")
        self.assertEqual(1, len(stored))
        self.assertIsNone(stored[0].turnover)


class ReadOnlyApiDoesNotIngestTest(unittest.TestCase):
    def test_public_api_does_not_call_ingestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "api.db")
            settings = AppSettings(
                app_mode="private", app_env="test", host="127.0.0.1", port=8000,
                database_path=db_path, log_level="INFO",
            )
            init_conn = init_db(db_path)
            init_conn.close()
            app = create_app(settings=settings, dashboard_config_path=os.path.join(tmp, "dash.json"))
            conn = connect(db_path)
            with conn:
                repository.insert_asset(conn, _asset("stock-1", "stock", "000001"))
            conn.close()
            client = TestClient(app)
            with mock.patch("backend.app.services.ingestion.ingest") as ingest_mock:
                client.get("/api/v1/assets")
                client.get("/api/v1/assets/stock-1/history")
                ingest_mock.assert_not_called()
            client.close()


if __name__ == "__main__":
    unittest.main()
