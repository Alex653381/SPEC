"""统一手动更新入口的离线测试。"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from unittest import mock

import scripts.update_data as update_data
from backend.app.services.update_service import classify_result_status


class UpdateDataTest(unittest.TestCase):
    def test_build_targets_route_to_correct_cli(self):
        targets = update_data.build_targets(["stock", "fund", "index", "etf"], None)
        self.assertEqual(
            ["pilot_import_stock.py", "pilot_import_fund.py", "pilot_import_benchmark.py", "pilot_import_etf.py"],
            [target["script"] for target in targets],
        )
        self.assertEqual(
            ["data/live-pilot.db", "data/live-fund-pilot.db", "data/live-benchmark.db", "data/live-etf-pilot.db"],
            [target["db"] for target in targets],
        )

    def test_resolve_window_explicit_and_auto(self):
        self.assertEqual(
            (date(2026, 1, 1), date(2026, 1, 31)),
            update_data.resolve_window(None, date(2026, 1, 1), date(2026, 1, 31)),
        )
        self.assertEqual(
            (date(2026, 10, 31), date.today()),
            update_data.resolve_window(date(2026, 10, 30), None, None),
        )

    def test_resolve_window_requires_explicit_when_empty(self):
        with self.assertRaises(ValueError):
            update_data.resolve_window(None, None, None)

    def test_parse_cli_json_ignores_prelude(self):
        parsed = update_data.parse_cli_json('pilot_database=x\nasset_code=1\n{"status": "ok"}')
        self.assertEqual({"status": "ok"}, parsed)

    def test_default_offline_does_not_run_target(self):
        argv = ["update_data.py", "--asset-type", "etf"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            update_data, "run_target"
        ) as run_mock:
            self.assertEqual(0, update_data.main())
        run_mock.assert_not_called()

    def test_live_rate_limit_stops_run(self):
        argv = [
            "update_data.py",
            "--asset-type",
            "etf",
            "--start",
            "2026-10-01",
            "--end",
            "2026-10-30",
            "--live",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            update_data, "run_target", return_value=(1, {"error_category": "rate_limit"})
        ):
            self.assertEqual(1, update_data.main())

    def test_run_target_builds_live_command(self):
        target = update_data.build_targets(["etf"], None)[0]
        args = argparse_args()
        with mock.patch("scripts.update_data.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = '{"status": "success"}'
            run_mock.return_value.stderr = ""
            update_data.run_target(target, date(2026, 10, 1), date(2026, 10, 30), args)
        command = run_mock.call_args.args[0]
        self.assertTrue(any("pilot_import_etf.py" in part for part in command))
        self.assertIn("--live", command)

    def test_classify_result_status(self):
        self.assertEqual("updated", classify_result_status("success", {"inserted": 2}))
        self.assertEqual("no_new_data", classify_result_status("success", {"inserted": 0}))
        self.assertEqual(
            "difference_reported",
            classify_result_status("success", {"inserted": 0, "changed_count": 1}),
        )
        self.assertEqual("failed", classify_result_status("failed", {"inserted": 1}))


def argparse_args():
    return type(
        "Args",
        (),
        {"retries": 2, "backoff": 1.0},
    )()


if __name__ == "__main__":
    unittest.main()
