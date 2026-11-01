"""只读 API 端到端测试。所有数据均为合成测试样本。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.core.config import AppSettings
from backend.app.db import repository
from backend.app.db.database import connect, init_db
from backend.app.schemas.records import AssetRecord
from backend.app.services.analysis_access import SourceDb
from backend.tests.support import make_bar, make_nav


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "api-test.db")
        self.dashboard_path = os.path.join(self.tmp.name, "default-dashboard.json")
        settings = AppSettings(
            app_mode="private",
            app_env="test",
            host="127.0.0.1",
            port=8000,
            database_path=self.db_path,
            log_level="INFO",
        )
        conn = init_db(self.db_path)
        conn.close()
        self.app = create_app(
            settings=settings,
            dashboard_config_path=self.dashboard_path,
            analysis_sources={
                asset_type: [SourceDb(path=self.db_path, label="test")]
                for asset_type in ("stock", "index", "etf", "open_fund")
            },
        )
        self.client = TestClient(self.app)
        self._seed()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def _seed(self):
        conn = connect(self.db_path)
        try:
            with conn:
                repository.insert_asset(
                    conn,
                    AssetRecord(
                        id="stock-000001",
                        symbol="000001",
                        name="SYN-PINGAN",
                        asset_type="stock",
                        market="SZ",
                        provider="synthetic",
                        provider_symbol="sz000001",
                        price_semantics="close",
                        volume_unit="shares",
                        adjustment_mode="qfq",
                    ),
                )
                repository.insert_asset(
                    conn,
                    AssetRecord(
                        id="index-000001",
                        symbol="000001",
                        name="SYN-SHINDEX",
                        asset_type="index",
                        market="SH",
                        provider="synthetic",
                        provider_symbol="sh000001",
                        price_semantics="index_points",
                        volume_unit="shares",
                        adjustment_mode=None,
                    ),
                )
                repository.insert_asset(
                    conn,
                    AssetRecord(
                        id="etf-510300",
                        symbol="510300",
                        name="SYN-HS300ETF",
                        asset_type="etf",
                        market="SH",
                        provider="synthetic",
                        provider_symbol="sh510300",
                        price_semantics="close",
                        volume_unit="shares",
                        adjustment_mode=None,
                    ),
                )
                repository.insert_asset(
                    conn,
                    AssetRecord(
                        id="fund-110022",
                        symbol="110022",
                        name="SYN-CONSUME",
                        asset_type="open_fund",
                        market="CN",
                        provider="synthetic",
                        provider_symbol="110022",
                        price_semantics="unit_nav",
                        volume_unit=None,
                        adjustment_mode=None,
                    ),
                )

                repository.insert_daily_bars(
                    conn,
                    [
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 2), close=10.0),
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 4), close=10.5),
                    ],
                )
                repository.insert_daily_bars(
                    conn,
                    [make_bar(asset_id="index-000001", trade_date=date(2024, 1, 2), close=3000.0, turnover=None)],
                )
                repository.insert_fund_navs(
                    conn,
                    [
                        make_nav(asset_id="fund-110022", nav_date=date(2024, 1, 2), unit_nav=1.5),
                        make_nav(asset_id="fund-110022", nav_date=date(2024, 1, 3), unit_nav=1.52),
                    ],
                )
        finally:
            conn.close()

    def test_health_ok_and_does_not_leak_path(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(200, resp.status_code)
        body = resp.json()
        self.assertEqual("ok", body["status"])
        self.assertEqual("private", body["app_mode"])
        self.assertFalse(body["authentication_implemented"])
        self.assertNotIn(self.db_path, json.dumps(body))

    def test_health_reports_database_error(self):
        self.app.state.database_path = os.path.join(self.tmp.name, "missing", "x.db")
        resp = self.client.get("/api/v1/health")
        self.assertEqual(503, resp.status_code)
        self.assertEqual("error", resp.json()["database"])

    def test_asset_list_filter_search_and_pagination(self):
        all_resp = self.client.get("/api/v1/assets")
        self.assertEqual(4, all_resp.json()["total"])

        filtered = self.client.get("/api/v1/assets", params={"asset_type": "index"})
        self.assertEqual(1, filtered.json()["total"])
        self.assertEqual("index", filtered.json()["items"][0]["asset_type"])

        searched = self.client.get("/api/v1/assets", params={"q": "PINGAN"})
        self.assertEqual(1, searched.json()["total"])
        self.assertEqual("stock-000001", searched.json()["items"][0]["id"])

        paged = self.client.get("/api/v1/assets", params={"limit": 1, "offset": 1})
        self.assertEqual(1, len(paged.json()["items"]))
        self.assertEqual(4, paged.json()["total"])

    def test_asset_detail_and_same_code_are_not_confused(self):
        stock = self.client.get("/api/v1/assets/stock-000001").json()
        index = self.client.get("/api/v1/assets/index-000001").json()
        self.assertEqual("000001", stock["symbol"])
        self.assertEqual("000001", index["symbol"])
        self.assertNotEqual(stock["id"], index["id"])

    def test_asset_detail_404(self):
        resp = self.client.get("/api/v1/assets/not-exists")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("ASSET_NOT_FOUND", resp.json()["error"]["code"])

    def test_daily_bar_history_is_ascending_and_no_zero_fill(self):
        resp = self.client.get(
            "/api/v1/assets/stock-000001/history",
            params={"start_date": "2024-01-02", "end_date": "2024-01-05"},
        )
        self.assertEqual(200, resp.status_code)
        body = resp.json()
        self.assertEqual("daily_bar", body["data_class"])
        self.assertEqual(2, body["count"])
        dates = [r["date"] for r in body["records"]]
        self.assertEqual(["2024-01-02", "2024-01-04"], dates)

    def test_fund_nav_history_has_no_ohlc(self):
        resp = self.client.get(
            "/api/v1/assets/fund-110022/history",
            params={"start_date": "2024-01-01", "end_date": "2024-01-04"},
        )
        body = resp.json()
        self.assertEqual("fund_nav", body["data_class"])
        self.assertEqual(2, body["count"])
        self.assertNotIn("open", body["records"][0])
        self.assertIn("unit_nav", body["records"][0])

    def test_invalid_date_and_reversed_range(self):
        bad_date = self.client.get(
            "/api/v1/assets/stock-000001/history", params={"start_date": "2024/01/02"}
        )
        self.assertEqual(400, bad_date.status_code)
        self.assertEqual("INVALID_DATE_RANGE", bad_date.json()["error"]["code"])

        reversed_range = self.client.get(
            "/api/v1/assets/stock-000001/history",
            params={"start_date": "2024-02-01", "end_date": "2024-01-01"},
        )
        self.assertEqual(400, reversed_range.status_code)

    def test_invalid_limit_is_rejected(self):
        resp = self.client.get("/api/v1/assets", params={"limit": 9999})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("INVALID_LIMIT", resp.json()["error"]["code"])

    def test_empty_range_returns_empty_records(self):
        resp = self.client.get(
            "/api/v1/assets/stock-000001/history",
            params={"start_date": "2030-01-01", "end_date": "2030-01-31"},
        )
        self.assertEqual(200, resp.status_code)
        self.assertEqual(0, resp.json()["count"])
        self.assertEqual([], resp.json()["records"])

    def test_get_requests_do_not_write_or_create_tasks(self):
        before = self._count_rows()
        self.client.get("/api/v1/assets")
        self.client.get("/api/v1/assets/stock-000001/history", params={"start_date": "2024-01-01"})
        self.client.get("/api/v1/dashboard/default")
        after = self._count_rows()
        self.assertEqual(before, after)

    def test_error_responses_do_not_leak_traceback(self):
        resp = self.client.get("/api/v1/assets/stock-000001/history", params={"start_date": "bad"})
        text = resp.text.lower()
        self.assertNotIn("traceback", text)
        self.assertNotIn(self.db_path, text)

    def test_dashboard_config_absent_and_present(self):
        absent = self.client.get("/api/v1/dashboard/default").json()
        self.assertFalse(absent["configured"])
        self.assertEqual([], absent["assets"])

        with open(self.dashboard_path, "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"symbol": "000001", "market": "SZ", "asset_type": "stock"}]}, fh)
        present = self.client.get("/api/v1/dashboard/default").json()
        self.assertTrue(present["configured"])
        self.assertEqual(1, len(present["assets"]))

    def _count_rows(self):
        conn = connect(self.db_path)
        try:
            tables = ("assets", "daily_bars", "fund_nav", "data_gaps", "data_quality_audit", "asset_update_state")
            total = 0
            for table in tables:
                total += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return total
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
