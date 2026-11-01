"""真实基准资产导入的离线测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

import scripts.pilot_import_benchmark as benchmark_cli
from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.providers.tencent import TencentIndexAdapter
from backend.app.workers.jobs import TaskExecutionError
from backend.app.workers.live_import import import_live_daily_incremental
from backend.tests.support import make_asset, make_bar


class BenchmarkImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "benchmark.db")
        self.conn = init_db(self.path)
        with self.conn:
            repository.insert_asset(self.conn, make_asset("index-sh000001", "index", "000001"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_index_import_uses_daily_pipeline(self):
        bars = [
            make_bar(
                asset_id="index-sh000001",
                trade_date=date(2026, 10, 1),
                open_=3000,
                high=3010,
                low=2990,
                close=3005,
                volume=1000,
                turnover=None,
                adjustment_mode="none",
                provider="tencent",
            )
        ]
        result = import_live_daily_incremental(self.conn, "index-sh000001", "index", bars)
        self.assertEqual(1, result["inserted"])
        rows = repository.query_daily_bars(self.conn, "index-sh000001")
        self.assertEqual("none", rows[0].adjustment_mode)
        self.assertIsNone(rows[0].turnover)

    def test_index_quality_failure_rejects(self):
        bars = [
            make_bar(
                asset_id="index-sh000001",
                trade_date=date(2026, 10, 1),
                open_=0,
                high=0,
                low=0,
                close=0,
                volume=100,
                adjustment_mode="none",
            )
        ]
        with self.assertRaises(TaskExecutionError):
            import_live_daily_incremental(self.conn, "index-sh000001", "index", bars)
        self.assertEqual([], repository.query_daily_bars(self.conn, "index-sh000001"))

    def test_tencent_amount_is_volume_not_turnover(self):
        adapter = TencentIndexAdapter(
            lambda *_: [{"date": "2026-10-01", "open": 3000, "high": 3010, "low": 2990, "close": 3005, "amount": 1234}]
        )
        record = adapter.fetch_history("index-sh000001").records[0]
        self.assertEqual(1234.0, record.volume)
        self.assertIsNone(record.turnover)


class BenchmarkPathGuardTest(unittest.TestCase):
    def test_other_databases_are_rejected(self):
        for name in ("live-pilot.db", "live-fund-pilot.db", "demo-synthetic.db"):
            with self.assertRaises(ValueError):
                benchmark_cli.resolve_benchmark_path(os.path.join(benchmark_cli.ROOT, "data", name))

    def test_benchmark_database_is_accepted(self):
        self.assertEqual(
            os.path.normcase(benchmark_cli.expected_benchmark_path()),
            os.path.normcase(
                benchmark_cli.resolve_benchmark_path(
                    os.path.join(benchmark_cli.ROOT, "data", "live-benchmark.db")
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
