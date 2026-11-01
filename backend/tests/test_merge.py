"""合并去重与异常数据保护测试。"""

from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.merge import merge_daily_bars
from backend.tests.support import make_bar


class MergeTest(unittest.TestCase):
    def test_duplicate_import_is_idempotent(self):
        existing = [make_bar(trade_date=date(2024, 1, 2))]
        incoming = [make_bar(trade_date=date(2024, 1, 2))]
        merged, conflicts = merge_daily_bars(existing, incoming)
        self.assertEqual(1, len(merged))
        self.assertEqual([], conflicts)

    def test_new_date_is_appended(self):
        existing = [make_bar(trade_date=date(2024, 1, 2))]
        incoming = [make_bar(trade_date=date(2024, 1, 3))]
        merged, conflicts = merge_daily_bars(existing, incoming)
        self.assertEqual(2, len(merged))
        self.assertEqual([], conflicts)

    def test_incoming_does_not_overwrite_existing_by_default(self):
        existing = [make_bar(trade_date=date(2024, 1, 2), close=10.2)]
        incoming = [make_bar(trade_date=date(2024, 1, 2), close=999.0)]
        merged, conflicts = merge_daily_bars(existing, incoming, preserve_existing=True)
        self.assertEqual(10.2, merged[0].close)
        self.assertEqual(1, len(conflicts))
        self.assertEqual("existing preserved", conflicts[0].reason)


if __name__ == "__main__":
    unittest.main()
