"""应用配置测试。"""

from __future__ import annotations

import importlib
import unittest
from unittest import mock

from backend.app.core import config


class ConfigTest(unittest.TestCase):
    def test_defaults_are_private_and_loopback(self):
        settings = config.load_settings({})
        self.assertEqual("private", settings.app_mode)
        self.assertEqual("development", settings.app_env)
        self.assertEqual("127.0.0.1", settings.host)
        self.assertEqual(8000, settings.port)
        self.assertEqual("data/market-research.db", settings.database_path)
        self.assertEqual("INFO", settings.log_level)

    def test_env_values_override_defaults(self):
        settings = config.load_settings(
            {
                "APP_MODE": "private",
                "APP_ENV": "test",
                "HOST": "127.0.0.1",
                "PORT": "9001",
                "DATABASE_PATH": "/tmp/test.db",
                "LOG_LEVEL": "DEBUG",
            }
        )
        self.assertEqual("test", settings.app_env)
        self.assertEqual(9001, settings.port)
        self.assertEqual("/tmp/test.db", settings.database_path)
        self.assertEqual("DEBUG", settings.log_level)

    def test_invalid_mode_fails_loudly(self):
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"APP_MODE": "internal"})

    def test_invalid_env_fails_loudly(self):
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"APP_ENV": "staging"})

    def test_invalid_port_fails_loudly(self):
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"PORT": "not-a-number"})
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"PORT": "70000"})

    def test_invalid_log_level_fails_loudly(self):
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"LOG_LEVEL": "VERBOSE"})

    def test_public_mode_is_rejected_in_production(self):
        with self.assertRaises(config.ConfigurationError):
            config.load_settings({"APP_ENV": "production", "APP_MODE": "public"})

    def test_import_has_no_service_side_effects(self):
        with mock.patch("socket.socket") as socket_mock, mock.patch("threading.Thread.start") as thread_mock:
            importlib.reload(config)
            socket_mock.assert_not_called()
            thread_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
