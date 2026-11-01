"""合成数据从 SQLite 到只读 API 的端到端测试。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.core.config import AppSettings
from backend.app.db.database import connect, init_db
from backend.app.services.analysis_access import SourceDb
from backend.tests import fixtures


class SyntheticE2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "e2e.db")
        self.dashboard_path = os.path.join(self.tmp.name, "dashboard.json")
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
        conn = connect(self.db_path)
        try:
            fixtures.seed_database(conn)
        finally:
            conn.close()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_health(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("ok", resp.json()["status"])
        self.assertEqual("private", resp.json()["app_mode"])

    def test_asset_list_and_detail(self):
        listing = self.client.get("/api/v1/assets").json()
        self.assertEqual(4, listing["total"])
        detail = self.client.get("/api/v1/assets/stock-000001").json()
        self.assertEqual("stock", detail["asset_type"])
        self.assertEqual("000001", detail["symbol"])

    def test_stock_history_range_order_and_gap(self):
        days = fixtures.trading_days()
        missing = {days[6], days[7]}
        resp = self.client.get(
            "/api/v1/assets/stock-000001/history",
            params={"start_date": days[0].isoformat(), "end_date": days[-1].isoformat()},
        )
        body = resp.json()
        self.assertEqual("daily_bar", body["data_class"])
        returned = [r["date"] for r in body["records"]]
        self.assertEqual(returned, sorted(returned))
        self.assertNotIn(days[6].isoformat(), returned)
        self.assertNotIn(days[7].isoformat(), returned)
        self.assertEqual(len(days) - len(missing), body["count"])

    def test_fund_history_has_nav_not_ohlc(self):
        days = fixtures.trading_days()
        resp = self.client.get(
            "/api/v1/assets/fund-110022/history",
            params={"start_date": days[0].isoformat(), "end_date": days[-1].isoformat()},
        )
        body = resp.json()
        self.assertEqual("fund_nav", body["data_class"])
        self.assertNotIn("open", body["records"][0])
        self.assertNotIn("volume", body["records"][0])
        self.assertIn("unit_nav", body["records"][0])

    def test_dashboard_default_absent_and_present(self):
        absent = self.client.get("/api/v1/dashboard/default").json()
        self.assertFalse(absent["configured"])
        self.assertEqual([], absent["assets"])

        with open(self.dashboard_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "assets": [
                        {"symbol": "000001", "market": "SZ", "asset_type": "stock"},
                        {"symbol": "000001", "market": "SH", "asset_type": "index"},
                    ]
                },
                fh,
            )
        present = self.client.get("/api/v1/dashboard/default").json()
        self.assertTrue(present["configured"])
        self.assertEqual(2, len(present["assets"]))


if __name__ == "__main__":
    unittest.main()
