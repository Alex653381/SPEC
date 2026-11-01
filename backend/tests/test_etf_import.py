"""真实 ETF 数据接入的离线测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

import scripts.pilot_import_etf as etf_cli
from backend.app.db import repository
from backend.app.db.database import connect, init_db
from backend.app.providers.eastmoney import EastmoneyETFAdapter
from backend.app.workers.live_import import import_live_daily_incremental
from backend.tests.support import make_asset, make_bar


ETF_ROW = {
    "日期": "2026-10-19",
    "开盘": 4.0,
    "收盘": 4.05,
    "最高": 4.08,
    "最低": 3.98,
    "成交量": 5000,
    "成交额": 20250,
}


class EtfImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "etf.db")
        self.conn = init_db(self.path)
        with self.conn:
            repository.insert_asset(self.conn, make_asset("etf-510300-live", "etf", "510300"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_adapter_maps_fields(self):
        adapter = EastmoneyETFAdapter(lambda *_: [ETF_ROW])
        record = adapter.fetch_history("etf-510300-live").records[0]
        self.assertEqual(4.0, record.open)
        self.assertEqual(4.05, record.close)
        self.assertEqual(5000.0, record.volume)
        self.assertEqual(20250.0, record.turnover)
        self.assertEqual("none", record.adjustment_mode)

    def test_first_and_repeat_import(self):
        bars = [
            make_bar(
                asset_id="etf-510300-live",
                trade_date=date(2026, 10, 19),
                open_=4.0,
                high=4.08,
                low=3.98,
                close=4.05,
                volume=5000,
                turnover=20250,
                adjustment_mode="none",
                provider="eastmoney_push2his",
            )
        ]
        first = import_live_daily_incremental(self.conn, "etf-510300-live", "etf", bars)
        self.assertEqual(1, first["inserted"])
        second = import_live_daily_incremental(self.conn, "etf-510300-live", "etf", bars)
        self.assertEqual(0, second["inserted"])
        self.assertEqual(1, second["unchanged_count"])

    def test_path_guard_rejects_other_databases(self):
        for name in ("live-pilot.db", "live-fund-pilot.db", "live-benchmark.db", "demo-synthetic.db"):
            with self.assertRaises(ValueError):
                etf_cli.resolve_etf_path(os.path.join(etf_cli.ROOT, "data", name))


class EtfApiTest(unittest.TestCase):
    def test_api_reads_etf_from_pilot_source(self):
        from fastapi.testclient import TestClient

        from backend.app.api.app import create_app
        from backend.app.core.config import AppSettings
        from backend.app.services.analysis_access import SourceDb

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = os.path.join(tmp, "etf-api.db")
            init_db(db_path)
            conn = connect(db_path)
            with conn:
                repository.insert_asset(
                    conn,
                    make_asset("etf-510300-live", "etf", "510300"),
                )
                repository.insert_daily_bars(
                    conn,
                    [
                        make_bar(
                            asset_id="etf-510300-live",
                            trade_date=date(2026, 10, 19),
                            close=4.05,
                            adjustment_mode="none",
                            provider="eastmoney_push2his",
                        )
                    ],
                )
            conn.close()
            settings = AppSettings(
                app_mode="private",
                app_env="test",
                host="127.0.0.1",
                port=8000,
                database_path=db_path,
                log_level="INFO",
            )
            app = create_app(
                settings=settings,
                dashboard_config_path=os.path.join(tmp, "d.json"),
                analysis_sources={
                    asset_type: [SourceDb(path=db_path, label="test")]
                    for asset_type in ("stock", "index", "etf", "open_fund")
                },
            )
            client = TestClient(app)
            listing = client.get("/api/v1/assets", params={"asset_type": "etf"}).json()
            self.assertEqual(1, listing["total"])
            history = client.get("/api/v1/assets/etf-510300-live/history").json()
            self.assertEqual("daily_bar", history["data_class"])
            self.assertEqual(1, history["count"])
            client.close()


if __name__ == "__main__":
    unittest.main()
