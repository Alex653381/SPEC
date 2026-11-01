"""数据质量检查模块测试。"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from backend.app.db.database import init_db
from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.schemas.records import DailyBarRecord, FundNavRecord
from backend.tests.support import make_asset, make_bar, make_nav


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class QualityRulesTest(unittest.TestCase):
    def test_clean_records_pass(self):
        report = check_records(
            [make_bar(), make_bar(asset_id="index-000001", turnover=None, adjustment_mode="none")],
            [make_nav()],
            {"index-000001": "index", "fund-110022": "open_fund", "asset_stock_000001": "stock"},
        )
        self.assertTrue(report.completed)
        self.assertEqual(0, report.issue_count)

    def test_duplicate_dates_are_reported(self):
        report = check_records([make_bar(), make_bar()], [])
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_008" for issue in report.issues))

    def test_invalid_and_missing_fields(self):
        bad = DailyBarRecord(
            asset_id="stock-000001",
            trade_date=None,
            open=math.nan,
            high=10,
            low=9,
            close=10,
            volume=1000,
            adjustment_mode="qfq",
            provider="synthetic",
            fetched_at=make_bar().fetched_at,
        )
        report = check_records([bad], [])
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_002" for issue in report.issues))
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_003" for issue in report.issues))

    def test_ohlc_and_negative_volume(self):
        bad = DailyBarRecord(
            asset_id="stock-000001",
            trade_date=date(2024, 1, 2),
            open=10,
            high=9,
            low=11,
            close=10,
            volume=-1,
            adjustment_mode="qfq",
            provider="synthetic",
            fetched_at=make_bar().fetched_at,
        )
        report = check_records([bad], [])
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_005" for issue in report.issues))
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_004" for issue in report.issues))

    def test_fund_nav_invalid_value(self):
        bad = FundNavRecord(
            asset_id="fund-110022",
            nav_date=date(2024, 1, 2),
            unit_nav=0,
            provider="synthetic",
            fetched_at=make_nav().fetched_at,
        )
        report = check_records([], [bad])
        self.assertTrue(any(issue.rule_id == "DQ_NAV_004" for issue in report.issues))

    def test_missing_trading_day_is_not_an_error(self):
        report = check_records(
            [make_bar(trade_date=date(2024, 1, 2)), make_bar(trade_date=date(2024, 1, 4))],
            [],
        )
        self.assertEqual(0, report.issue_count)

    def test_large_price_move_is_warning_not_error(self):
        report = check_records(
            [
                make_bar(trade_date=date(2024, 1, 2), close=10.0),
                make_bar(
                    trade_date=date(2024, 1, 3),
                    open_=12.5,
                    high=13.2,
                    low=12.4,
                    close=13.0,
                ),
            ],
            [],
        )
        self.assertTrue(any(issue.rule_id == "DQ_DAILY_009" for issue in report.issues))
        self.assertEqual(0, report.by_severity["error"])
        self.assertEqual(1, report.by_severity["warning"])

    def test_large_nav_move_is_warning_not_error(self):
        report = check_records(
            [],
            [
                make_nav(nav_date=date(2024, 1, 2), unit_nav=1.0),
                make_nav(nav_date=date(2024, 1, 3), unit_nav=1.2),
            ],
        )
        self.assertTrue(any(issue.rule_id == "DQ_NAV_006" for issue in report.issues))
        self.assertEqual(0, report.by_severity["error"])
        self.assertEqual(1, report.by_severity["warning"])

    def test_report_is_stable_and_read_only(self):
        bars = [make_bar(trade_date=date(2024, 1, 2)), make_bar(trade_date=date(2024, 1, 2))]
        before = [bar.quality_status for bar in bars]
        first = check_records(bars, [])
        second = check_records(bars, [])
        self.assertEqual(
            [issue.rule_id for issue in first.issues],
            [issue.rule_id for issue in second.issues],
        )
        self.assertEqual(before, [bar.quality_status for bar in bars])


class QualityCliTest(unittest.TestCase):
    def test_cli_reports_issues_with_zero_exit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "quality.db")
            conn = init_db(path)
            with conn:
                repository.insert_asset(conn, make_asset("stock-000001", "stock", "000001"))
                repository.insert_daily_bars(conn, [make_bar(asset_id="stock-000001", volume=-1)])
            conn.close()
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "quality_check.py"), "--db", path],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("issue_count: 1", result.stdout)

    def test_cli_missing_db_returns_nonzero(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "quality_check.py"), "--db", "missing.db"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)

    def test_cli_incompatible_schema_returns_nonzero(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "bad.db")
            open(path, "w").close()
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "quality_check.py"), "--db", path],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
