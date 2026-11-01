"""访问策略接口。

私有模式只表达“不对外公开”，不代表已经完成身份认证。认证尚未实现时，
任何对外访问都不能被标记为安全。
"""

from __future__ import annotations

from backend.app.core.config import APP_MODE_PRIVATE, APP_MODE_PUBLIC


AUTHENTICATION_IMPLEMENTED = False


class Operation:
    READ_ONLY = "read_only"
    ADMIN = "admin"
    FETCH = "fetch"


def requires_authentication(app_mode: str) -> bool:
    """私有模式需要认证；公开模式允许匿名只读。"""
    return app_mode == APP_MODE_PRIVATE


def guest_can_access(app_mode: str, operation: str) -> bool:
    """未认证请求的访问规则。"""
    if operation != Operation.READ_ONLY:
        return False
    return app_mode == APP_MODE_PUBLIC


def external_access_is_safe(app_mode: str) -> bool:
    """认证机制未实现前，对外访问一律视为不安全。"""
    return False
