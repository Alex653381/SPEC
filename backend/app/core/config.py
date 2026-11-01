"""应用配置。仅从环境变量读取，导入模块时不会启动服务或后台任务。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


APP_MODE_PRIVATE = "private"
APP_MODE_PUBLIC = "public"

VALID_MODES = (APP_MODE_PRIVATE, APP_MODE_PUBLIC)
VALID_ENVS = ("development", "test", "production")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigurationError(ValueError):
    """配置值非法时抛出，不静默降级。"""


@dataclass(frozen=True)
class AppSettings:
    app_mode: str
    app_env: str
    host: str
    port: int
    database_path: str
    log_level: str


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    source = os.environ if env is None else env

    app_mode = str(source.get("APP_MODE", APP_MODE_PRIVATE)).strip().lower()
    if app_mode not in VALID_MODES:
        raise ConfigurationError(f"APP_MODE 必须为 {'/'.join(VALID_MODES)}，当前为 {app_mode!r}")

    app_env = str(source.get("APP_ENV", "development")).strip().lower()
    if app_env not in VALID_ENVS:
        raise ConfigurationError(f"APP_ENV 必须为 {'/'.join(VALID_ENVS)}，当前为 {app_env!r}")

    host = str(source.get("HOST", "127.0.0.1")).strip()
    if not host:
        raise ConfigurationError("HOST 不能为空")

    port_raw = str(source.get("PORT", "8000")).strip()
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigurationError(f"PORT 必须是整数，当前为 {port_raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"PORT 必须在 1-65535，当前为 {port}")

    database_path = str(source.get("DATABASE_PATH", "data/market-research.db")).strip()
    if not database_path:
        raise ConfigurationError("DATABASE_PATH 不能为空")

    log_level = str(source.get("LOG_LEVEL", "INFO")).strip().upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigurationError(f"LOG_LEVEL 必须为 {'/'.join(VALID_LOG_LEVELS)}，当前为 {log_level!r}")

    if app_env == "production" and app_mode == APP_MODE_PUBLIC:
        raise ConfigurationError(
            "生产环境禁止使用 APP_MODE=public，直到访问控制已实现并显式启用"
        )

    return AppSettings(
        app_mode=app_mode,
        app_env=app_env,
        host=host,
        port=port,
        database_path=database_path,
        log_level=log_level,
    )
