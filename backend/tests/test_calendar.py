"""交易日历与缺口检测测试。"""

from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.calendar import build_calendar, detect_gaps, partition_fund_nav
from backend.tests.support import make_nav


class CalendarTest(unittest.TestCase):
    def test_detect_gaps_marks_missing_trading_days(self):
        calendar = build_calendar(
            [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
        )
        present = [date(2024, 1, 2)]
        gaps = detect_gaps(present, calendar, start=date(2024, 1, 1), end=date(2024, 1, 4))
        self.assertEqual(
            [(g.start.isoformat(), g.end.isoformat()) for g in gaps],
            [("2024-01-01", "2024-01-01"), ("2024-01-03", "2024-01-04")],
        )

    def test_partition_fund_nav_keeps_all_without_explicit_rule(self):
        records = [
            make_nav(nav_date=date(2024, 1, 2)),
            make_nav(nav_date=date(2024, 1, 3)),
            make_nav(nav_date=date(2024, 1, 6)),  # 周六占位行
        ]
        valid, placeholders = partition_fund_nav(records)
        self.assertEqual(3, len(valid))
        self.assertEqual([], placeholders)

    def test_partition_fund_nav_isolates_explicit_placeholders(self):
        records = [
            make_nav(nav_date=date(2024, 1, 2)),
            make_nav(nav_date=date(2024, 1, 3)),
            make_nav(nav_date=date(2024, 1, 6)),
        ]
        valid, placeholders = partition_fund_nav(records, {date(2024, 1, 6)})
        self.assertEqual(2, len(valid))
        self.assertEqual([date(2024, 1, 6)], [record.nav_date for record in placeholders])


if __name__ == "__main__":
    unittest.main()
