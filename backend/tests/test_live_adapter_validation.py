"""真实股票日线只读验证路径的离线测试。全部使用 mock fetcher，不联网、不写库。"""

from __future__ import annotations

import io
import sys
import unittest
from datetime import date
from unittest.mock import patch

import scripts.validate_live_adapters as cli
from backend.app.db import repository
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    is_retryable_error,
    redact_error_detail,
)
from scripts.validate_live_adapters import run_stock


STOCK_ROW = {
    "date": "2024-01-02",
    "open": 10.0,
    "high": 10.5,
    "low": 9.8,
    "close": 10.2,
    "volume": 1000,
    "amount": 10200,
}


class StockLiveValidationTest(unittest.TestCase):
    def test_normal_response_summary(self):
        calls = []

        def fetcher(code, start, end):
            calls.append((code, start, end))
            return [STOCK_ROW]

        summary = run_stock(
            date(2024, 1, 1), date(2024, 1, 31), code="sz000001", retries=0, fetcher=fetcher
        )
        self.assertEqual(("sz000001", date(2024, 1, 1), date(2024, 1, 31)), calls[0])
        self.assertEqual(1, summary["converted_rows"])
        self.assertEqual(0, summary["quality"]["issue_count"])
        self.assertEqual("qfq", summary["adjustment_mode"])
        self.assertEqual("2024-01-02", summary["date_min"])
        self.assertEqual("2024-01-02", summary["date_max"])
        self.assertFalse(summary["database_written"])
        self.assertEqual(1, summary["attempts"])

    def test_empty_response_is_success_with_zero_rows(self):
        summary = run_stock(
            date(2024, 1, 1),
            date(2024, 1, 31),
            code="sz000001",
            retries=0,
            fetcher=lambda *_: [],
        )
        self.assertEqual(0, summary["fetched_rows"])
        self.assertEqual(0, summary["converted_rows"])
        self.assertIsNone(summary["date_min"])
        self.assertIsNone(summary["date_max"])
        self.assertFalse(summary["database_written"])

    def test_timeout_is_classified_and_retried(self):
        def fetcher(*_):
            raise TimeoutError("timed out")

        summary = run_stock(
            date(2024, 1, 1),
            date(2024, 1, 31),
            code="sz000001",
            retries=2,
            fetcher=fetcher,
        )
        self.assertEqual("error", summary["status"])
        self.assertEqual("timeout", summary["error_category"])
        self.assertEqual(3, summary["attempts"])
        self.assertFalse(summary["database_written"])

    def test_rate_limit_is_not_retried(self):
        def fetcher(*_):
            raise RuntimeError("429 rate limit")

        summary = run_stock(
            date(2024, 1, 1),
            date(2024, 1, 31),
            code="sz000001",
            retries=3,
            fetcher=fetcher,
        )
        self.assertEqual("error", summary["status"])
        self.assertEqual("rate_limit", summary["error_category"])
        self.assertEqual(1, summary["attempts"])
        self.assertFalse(summary["database_written"])

    def test_missing_required_field_is_reported_without_crash(self):
        row = dict(STOCK_ROW)
        row.pop("close")
        summary = run_stock(
            date(2024, 1, 1),
            date(2024, 1, 31),
            code="sz000001",
            retries=0,
            fetcher=lambda *_: [row],
        )
        self.assertEqual(0, summary["converted_rows"])
        self.assertEqual(1, summary["skipped_rows"])
        self.assertFalse(summary["database_written"])

    def test_quality_failure_is_reported_without_exception(self):
        row = {"date": "2024-01-02", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 100}
        summary = run_stock(
            date(2024, 1, 1),
            date(2024, 1, 31),
            code="sz000001",
            retries=0,
            fetcher=lambda *_: [row],
        )
        self.assertEqual(1, summary["converted_rows"])
        self.assertGreater(summary["quality"]["issue_count"], 0)
        self.assertTrue(any(i["rule_id"] == "DQ_DAILY_007" for i in summary["quality"]["issues"]))
        self.assertFalse(summary["database_written"])

    def test_validation_path_does_not_call_database_writes(self):
        with patch.object(
            repository, "insert_daily_bars", side_effect=AssertionError("数据库写入被调用")
        ):
            summary = run_stock(
                date(2024, 1, 1),
                date(2024, 1, 31),
                code="sz000001",
                retries=0,
                fetcher=lambda *_: [STOCK_ROW],
            )
        self.assertEqual(1, summary["converted_rows"])
        self.assertFalse(summary["database_written"])

    def test_offline_mode_does_not_invoke_network(self):
        out = io.StringIO()
        with patch.object(sys, "argv", ["validate_live_adapters.py", "--asset", "stock"]), patch.object(
            cli, "run_stock"
        ) as run_mock, patch.object(sys, "stdout", out):
            self.assertEqual(0, cli.main())
        run_mock.assert_not_called()
        self.assertIn('"live_request_executed": false', out.getvalue())


class ErrorClassificationTest(unittest.TestCase):
    def test_classify_and_redact(self):
        self.assertEqual("timeout", classify_error(TimeoutError("read timed out")))
        self.assertEqual("rate_limit", classify_error(RuntimeError("429 rate limit")))
        self.assertTrue(is_retryable_error("timeout"))
        self.assertFalse(is_retryable_error("rate_limit"))

        redacted = redact_error_detail(RuntimeError("token=abc123 cookie=xyz"))
        self.assertNotIn("abc123", redacted)
        self.assertIn("[redacted]", redacted)


class FetchRetryTest(unittest.TestCase):
    def test_transient_error_retries_then_succeeds(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("timed out")
            return "ok"

        with patch("backend.app.services.live_validation.time.sleep"):
            self.assertEqual("ok", fetch_with_retry(fn, retries=2, backoff=0.1))
        self.assertEqual(2, len(calls))

    def test_rate_limit_is_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise RuntimeError("429 rate limit")

        with patch("backend.app.services.live_validation.time.sleep"):
            with self.assertRaises(RuntimeError):
                fetch_with_retry(fn, retries=3, backoff=0.1)
        self.assertEqual(1, len(calls))

    def test_exhausts_retries(self):
        calls = []

        def fn():
            calls.append(1)
            raise TimeoutError("timed out")

        with patch("backend.app.services.live_validation.time.sleep"):
            with self.assertRaises(TimeoutError):
                fetch_with_retry(fn, retries=2, backoff=0.1)
        self.assertEqual(3, len(calls))


if __name__ == "__main__":
    unittest.main()
