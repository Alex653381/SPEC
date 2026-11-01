"""数据库迁移、写入、查询、回滚与备份测试。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date

from backend.app.db.database import backup_database, init_db
from backend.app.db.repository import (
    insert_asset,
    insert_daily_bars,
    insert_fund_navs,
    query_daily_bars,
    query_fund_navs,
)
from backend.tests.support import make_asset, make_bar, make_nav


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.db")
        self.conn = init_db(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_migrations_are_repeatable(self):
        self.conn.close()
        self.conn = init_db(self.path)
        versions = [r[0] for r in self.conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        self.assertEqual([1, 2, 3], versions)

    def test_daily_bar_write_and_query(self):
        asset = make_asset("asset_stock_000001", "stock")
        with self.conn:
            insert_asset(self.conn, asset)
            insert_daily_bars(self.conn, [make_bar()])
        rows = query_daily_bars(self.conn, "asset_stock_000001")
        self.assertEqual(1, len(rows))
        self.assertEqual(date(2024, 1, 2), rows[0].trade_date)

    def test_duplicate_write_without_replace_keeps_first(self):
        asset = make_asset("asset_stock_000001", "stock")
        with self.conn:
            insert_asset(self.conn, asset)
            insert_daily_bars(self.conn, [make_bar(close=10.0)])
            insert_daily_bars(self.conn, [make_bar(close=99.0)])
        rows = query_daily_bars(self.conn, "asset_stock_000001")
        self.assertEqual(1, len(rows))
        self.assertEqual(10.0, rows[0].close)

    def test_index_turnover_null_is_persisted(self):
        asset = make_asset("asset_index_000001", "index")
        with self.conn:
            insert_asset(self.conn, asset)
            insert_daily_bars(self.conn, [make_bar(asset_id="asset_index_000001", turnover=None)])
        row = query_daily_bars(self.conn, "asset_index_000001")[0]
        self.assertIsNone(row.turnover)

    def test_fund_nav_write_and_query(self):
        asset = make_asset("asset_fund_110022", "open_fund")
        with self.conn:
            insert_asset(self.conn, asset)
            insert_fund_navs(self.conn, [make_nav()])
        rows = query_fund_navs(self.conn, "asset_fund_110022")
        self.assertEqual(1, len(rows))
        self.assertEqual(1.5, rows[0].unit_nav)

    def test_transaction_rollback(self):
        asset = make_asset("asset_stock_000001", "stock")
        with self.conn:
            insert_asset(self.conn, asset)
        with self.assertRaises(RuntimeError):
            with self.conn:
                insert_daily_bars(self.conn, [make_bar(trade_date=date(2024, 1, 3))])
                raise RuntimeError("boom")
        self.assertEqual([], query_daily_bars(self.conn, "asset_stock_000001"))

    def test_backup_creates_queryable_snapshot(self):
        asset = make_asset("asset_stock_000001", "stock")
        with self.conn:
            insert_asset(self.conn, asset)
            insert_daily_bars(self.conn, [make_bar()])
        dest = os.path.join(self.tmp.name, "backup.db")
        backup_database(self.conn, dest)
        backup_conn = sqlite3.connect(dest)
        try:
            count = backup_conn.execute(
                "SELECT COUNT(*) FROM daily_bars WHERE asset_id = ?", ("asset_stock_000001",)
            ).fetchone()[0]
            self.assertEqual(1, count)
        finally:
            backup_conn.close()


if __name__ == "__main__":
    unittest.main()
