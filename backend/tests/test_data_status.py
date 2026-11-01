"""只读数据状态接口测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.core.config import AppSettings
from backend.app.db import repository
from backend.app.db.database import connect, init_db
from backend.app.schemas.records import AssetRecord
from backend.app.services.analysis_access import SourceDb
from backend.tests.support import make_bar


class DataStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, "status.db")
        init_db(self.db_path)
        self._seed()
        settings = AppSettings(
            app_mode="private",
            app_env="test",
            host="127.0.0.1",
            port=8000,
            database_path=self.db_path,
            log_level="INFO",
        )
        self.app = create_app(
            settings=settings,
            dashboard_config_path=os.path.join(self.tmp.name, "d.json"),
            analysis_sources={
                asset_type: [SourceDb(path=self.db_path, label="test")]
                for asset_type in ("stock", "index", "etf", "open_fund")
            },
        )
        self.client = TestClient(self.app)

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
                repository.insert_daily_bars(
                    conn,
                    [
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 2), close=10.0, adjustment_mode="qfq"),
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 2), close=11.0, adjustment_mode="none"),
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 5), close=10.5, adjustment_mode="qfq"),
                    ],
                )
        finally:
            conn.close()

    def test_status_lists_and_detects_duplicates(self):
        listing = self.client.get("/api/v1/data-status").json()
        self.assertEqual(1, len(listing["items"]))
        item = listing["items"][0]
        self.assertEqual(3, item["record_count"])
        self.assertEqual(["2024-01-02"], item["duplicate_dates"])
        self.assertEqual("2024-01-02", item["first_date"])
        self.assertEqual("2024-01-05", item["last_date"])
        self.assertEqual(4, item["calendar_days"])
        self.assertEqual("ok", item["assessment"])
        self.assertEqual("error", item["quality_status"])
        self.assertEqual(1, item["quality_by_severity"]["error"])

    def test_status_single_and_404(self):
        resp = self.client.get("/api/v1/data-status/stock-000001")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(3, resp.json()["record_count"])
        missing = self.client.get("/api/v1/data-status/not-exists")
        self.assertEqual(404, missing.status_code)

    def test_status_is_read_only(self):
        conn = connect(self.db_path)
        try:
            before = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            rows_before = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        finally:
            conn.close()

        self.client.get("/api/v1/data-status")
        self.client.get("/api/v1/data-status/stock-000001")

        conn = connect(self.db_path)
        try:
            after = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            rows_after = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(before, after)
        self.assertEqual(rows_before, rows_after)


if __name__ == "__main__":
    unittest.main()
