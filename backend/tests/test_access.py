"""访问策略测试。"""

from __future__ import annotations

import unittest

from backend.app.core import access


class AccessPolicyTest(unittest.TestCase):
    def test_private_mode_does_not_imply_authentication(self):
        self.assertTrue(access.requires_authentication("private"))
        self.assertFalse(access.guest_can_access("private", access.Operation.READ_ONLY))

    def test_public_mode_allows_anonymous_read_only(self):
        self.assertFalse(access.requires_authentication("public"))
        self.assertTrue(access.guest_can_access("public", access.Operation.READ_ONLY))

    def test_guest_cannot_fetch_or_admin_in_any_mode(self):
        for mode in ("private", "public"):
            self.assertFalse(access.guest_can_access(mode, access.Operation.FETCH))
            self.assertFalse(access.guest_can_access(mode, access.Operation.ADMIN))

    def test_external_access_is_not_safe_until_auth_is_implemented(self):
        self.assertFalse(access.AUTHENTICATION_IMPLEMENTED)
        self.assertFalse(access.external_access_is_safe("private"))
        self.assertFalse(access.external_access_is_safe("public"))


if __name__ == "__main__":
    unittest.main()
