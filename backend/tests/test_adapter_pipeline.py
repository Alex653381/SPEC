"""供应商原始响应到标准导入管线的确定性测试。"""

from __future__ import annotations

import tempfile
import unittest

from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.providers.sina import SinaStockAdapter
from backend.app.quality.checker import check_records
from backend.app.workers.synthetic_import import import_batch
from backend.tests.support import make_asset


SINA_ROWS = [
    {
        "date": "2024-01-02",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "volume": 1000,
        "amount": 10200,
    },
    {
        "date": "2024-01-03",
        "open": 10.2,
        "high": 10.6,
        "low": 10.0,
        "close": 10.4,
        "volume": 1100,
        "amount": 11440,
    },
]


class AdapterPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = f"{self.tmp.name}/pipeline.db"
        self.conn = init_db(self.path)
        with self.conn:
            repository.insert_asset(self.conn, make_asset("stock-000001", "stock", "000001"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_sina_response_reaches_quality_and_import(self):
        adapter = SinaStockAdapter(lambda *_: SINA_ROWS)
        result = adapter.fetch_history("stock-000001", start=None, end=None)
        self.assertEqual(2, len(result.records))
        self.assertEqual("sina", result.records[0].provider)
        self.assertEqual("qfq", result.records[0].adjustment_mode)

        quality = check_records(result.records, [], {"stock-000001": "stock"})
        self.assertEqual(0, quality.issue_count)

        outcome = import_batch(self.conn, "stock-000001", result.records, "daily_bar")
        self.assertEqual(2, outcome.inserted)
        self.assertEqual(0, outcome.skipped)
        self.assertEqual(0, outcome.conflicts)

        repeated = import_batch(self.conn, "stock-000001", result.records, "daily_bar")
        self.assertEqual(0, repeated.inserted)
        self.assertEqual(2, repeated.skipped)


if __name__ == "__main__":
    unittest.main()
