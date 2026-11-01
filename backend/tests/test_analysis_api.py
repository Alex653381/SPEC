"""分析接口的只读端到端测试。"""

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
from backend.tests.support import make_bar, make_nav


class AnalysisApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, "analysis.db")
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
            dashboard_config_path=os.path.join(self.tmp.name, "dashboard.json"),
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
                        adjustment_mode=None,
                    ),
                )
                repository.insert_daily_bars(
                    conn,
                    [
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 2), close=10.0),
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 3), close=10.5),
                        make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 4), close=11.0),
                    ],
                )
                repository.insert_fund_navs(
                    conn,
                    [
                        make_nav(asset_id="fund-110022", nav_date=date(2024, 1, 2), unit_nav=1.5),
                        make_nav(asset_id="fund-110022", nav_date=date(2024, 1, 3), unit_nav=1.52),
                        make_nav(asset_id="fund-110022", nav_date=date(2024, 1, 4), unit_nav=1.55),
                    ],
                )
        finally:
            conn.close()

    def test_asset_metrics(self):
        resp = self.client.get(
            "/api/v1/analysis/assets/stock-000001/metrics",
            params={"start_date": "2024-01-02", "end_date": "2024-01-04"},
        )
        self.assertEqual(200, resp.status_code)
        body = resp.json()
        self.assertEqual("close", body["metric"])
        self.assertEqual(3, body["count"])
        self.assertAlmostEqual(0.1, body["cumulative_return"], places=10)
        self.assertIsNotNone(body["max_drawdown"])

    def test_fund_metrics_use_unit_nav(self):
        resp = self.client.get("/api/v1/analysis/assets/fund-110022/metrics")
        self.assertEqual("unit_nav", resp.json()["metric"])
        self.assertEqual(3, resp.json()["count"])

    def test_compare(self):
        resp = self.client.post(
            "/api/v1/analysis/compare",
            json={
                "asset_id": "stock-000001",
                "benchmark_asset_id": "fund-110022",
            },
        )
        self.assertEqual(200, resp.status_code)
        self.assertEqual(3, resp.json()["count"])

    def test_portfolio_and_weight_validation(self):
        ok = self.client.post(
            "/api/v1/analysis/portfolio",
            json={
                "items": [
                    {"asset_id": "stock-000001", "weight": 50},
                    {"asset_id": "fund-110022", "weight": 50},
                ]
            },
        )
        self.assertEqual(200, ok.status_code)
        self.assertEqual(2, ok.json()["count"])

        bad = self.client.post(
            "/api/v1/analysis/portfolio",
            json={
                "items": [
                    {"asset_id": "stock-000001", "weight": 60},
                    {"asset_id": "fund-110022", "weight": 30},
                ]
            },
        )
        self.assertEqual(400, bad.status_code)
        self.assertEqual("INVALID_PORTFOLIO", bad.json()["error"]["code"])

    def test_asset_not_found(self):
        resp = self.client.get("/api/v1/analysis/assets/not-exists/metrics")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("ASSET_NOT_FOUND", resp.json()["error"]["code"])

    def test_analysis_is_read_only(self):
        before = self._count_rows()
        self.client.get("/api/v1/analysis/assets/stock-000001/metrics")
        self.client.post(
            "/api/v1/analysis/portfolio",
            json={"items": [{"asset_id": "stock-000001", "weight": 100}]},
        )
        after = self._count_rows()
        self.assertEqual(before, after)

    def test_read_only_analysis_does_not_change_schema(self):
        conn = connect(self.db_path)
        try:
            before_versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            before_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master ORDER BY name")}
        finally:
            conn.close()

        self.client.get("/api/v1/analysis/assets/stock-000001/metrics")
        self.client.post(
            "/api/v1/analysis/portfolio",
            json={"items": [{"asset_id": "stock-000001", "weight": 100}]},
        )

        conn = connect(self.db_path)
        try:
            after_versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            after_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master ORDER BY name")}
        finally:
            conn.close()
        self.assertEqual(before_versions, after_versions)
        self.assertEqual(before_tables, after_tables)

    def test_create_app_does_not_migrate_fresh_database(self):
        fresh_path = os.path.join(self.tmp.name, "fresh.db")
        settings = AppSettings(
            app_mode="private",
            app_env="test",
            host="127.0.0.1",
            port=8001,
            database_path=fresh_path,
            log_level="INFO",
        )
        create_app(settings=settings, dashboard_config_path=os.path.join(self.tmp.name, "d.json"))
        self.assertFalse(os.path.exists(fresh_path))

    def _count_rows(self):
        conn = connect(self.db_path)
        try:
            tables = ("assets", "daily_bars", "fund_nav", "jobs", "daily_bar_revisions")
            total = 0
            for table in tables:
                total += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return total
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
