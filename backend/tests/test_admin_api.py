"""本地数据管理接口测试。"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from backend.app.api.app import create_app
from backend.app.core.config import AppSettings
from backend.app.db.database import connect, init_db
from backend.app.services.analysis_access import SourceDb
from backend.app.services.update_service import UpdateJobManager


class AdminApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, "admin.db")
        init_db(self.db_path)
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
            dashboard_config_path=os.path.join(self.tmp.name, "d.json"),
            analysis_sources={
                asset_type: [SourceDb(path=self.db_path, label="test")]
                for asset_type in ("stock", "index", "etf", "open_fund")
            },
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_preflight_is_read_only(self):
        before = self._business_rows()
        resp = self.client.post(
            "/api/v1/admin/update/preflight",
            json={"asset_type": "stock", "start_date": "2026-10-01", "end_date": "2026-10-30"},
        )
        self.assertEqual(200, resp.status_code)
        self.assertIn("database", resp.json())
        self.assertEqual(before, self._business_rows())

    def test_invalid_asset_and_date_rejected(self):
        bad_type = self.client.post("/api/v1/admin/update/preflight", json={"asset_type": "crypto"})
        self.assertEqual(400, bad_type.status_code)
        bad_date = self.client.post(
            "/api/v1/admin/update/run",
            json={"asset_type": "stock", "start_date": "bad", "end_date": "2026-10-30"},
        )
        self.assertEqual(400, bad_date.status_code)

    def test_run_requires_explicit_range(self):
        resp = self.client.post("/api/v1/admin/update/run", json={"asset_type": "stock"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("MISSING_RANGE", resp.json()["error"]["code"])

    def test_run_rejects_non_local_origin(self):
        resp = self.client.post(
            "/api/v1/admin/update/run",
            json={"asset_type": "stock", "start_date": "2026-10-01", "end_date": "2026-10-30"},
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(403, resp.status_code)

    def test_run_creates_job(self):
        with mock.patch.object(
            self.app.state.update_jobs,
            "start",
            return_value={"id": "j1", "asset_type": "stock", "status": "running", "result": None},
        ):
            resp = self.client.post(
                "/api/v1/admin/update/run",
                json={"asset_type": "stock", "start_date": "2026-10-01", "end_date": "2026-10-30"},
            )
        self.assertEqual(200, resp.status_code)
        self.assertEqual("j1", resp.json()["id"])

    def test_status_refresh_does_not_trigger_update(self):
        with mock.patch("backend.app.services.update_service.run_asset_update") as run_mock:
            self.client.get("/api/v1/data-status")
        run_mock.assert_not_called()

    def test_register_requires_confirmation_and_validates(self):
        missing_confirm = self.client.post(
            "/api/v1/admin/assets/register",
            json={
                "asset_type": "stock",
                "code": "sz600519",
                "start_date": "2026-10-01",
                "end_date": "2026-10-30",
            },
        )
        self.assertEqual(400, missing_confirm.status_code)
        self.assertEqual("CONFIRM_REQUIRED", missing_confirm.json()["error"]["code"])

        bad_type = self.client.post(
            "/api/v1/admin/assets/register",
            json={
                "asset_type": "crypto",
                "code": "btc",
                "start_date": "2026-10-01",
                "end_date": "2026-10-30",
                "confirm": True,
            },
        )
        self.assertEqual(400, bad_type.status_code)

    def test_register_rejects_long_range_and_bad_origin(self):
        long_range = self.client.post(
            "/api/v1/admin/assets/register",
            json={
                "asset_type": "stock",
                "code": "sz600519",
                "start_date": "2026-01-01",
                "end_date": "2026-10-30",
                "confirm": True,
            },
        )
        self.assertEqual(400, long_range.status_code)

        bad_origin = self.client.post(
            "/api/v1/admin/assets/register",
            json={
                "asset_type": "stock",
                "code": "sz600519",
                "start_date": "2026-10-01",
                "end_date": "2026-10-30",
                "confirm": True,
            },
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(403, bad_origin.status_code)

    def test_expand_requires_confirmation_and_range_limit(self):
        missing_confirm = self.client.post(
            "/api/v1/admin/assets/expand",
            json={"asset_type": "stock", "code": "sz600519", "start_date": "2026-01-01", "end_date": "2026-02-01"},
        )
        self.assertEqual(400, missing_confirm.status_code)

        too_long = self.client.post(
            "/api/v1/admin/assets/expand",
            json={
                "asset_type": "stock",
                "code": "sz600519",
                "start_date": "2024-01-01",
                "end_date": "2026-01-01",
                "confirm": True,
            },
        )
        self.assertEqual(400, too_long.status_code)
        self.assertEqual("INVALID_RANGE", too_long.json()["error"]["code"])

    def test_same_asset_concurrency_blocked(self):
        manager = UpdateJobManager()
        release = threading.Event()

        def slow_update(*_args, **_kwargs):
            release.wait(timeout=2)
            return {"status": "success"}

        with mock.patch("backend.app.services.update_service.run_asset_update", side_effect=slow_update):
            first = manager.start("stock", __import__("datetime").date(2026, 10, 1), __import__("datetime").date(2026, 10, 30), 0, 0)
            self.assertEqual("running", first["status"])
            second = manager.start("stock", __import__("datetime").date(2026, 10, 1), __import__("datetime").date(2026, 10, 30), 0, 0)
            self.assertEqual("same_asset_running", second["error"])
            release.set()

    def _business_rows(self):
        conn = connect(self.db_path)
        try:
            tables = ("assets", "daily_bars", "fund_nav", "jobs")
            return sum(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
