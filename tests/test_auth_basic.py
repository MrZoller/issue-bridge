import base64
import unittest

from app.security import _parse_basic_auth_header


class BasicAuthParsingTests(unittest.TestCase):
    def test_parse_basic_auth_header_valid(self):
        token = base64.b64encode(b"user:pass").decode("ascii")
        creds = _parse_basic_auth_header(f"Basic {token}")
        self.assertIsNotNone(creds)
        assert creds is not None
        self.assertEqual(creds.username, "user")
        self.assertEqual(creds.password, "pass")

    def test_parse_basic_auth_header_invalid_scheme(self):
        token = base64.b64encode(b"user:pass").decode("ascii")
        creds = _parse_basic_auth_header(f"Bearer {token}")
        self.assertIsNone(creds)

    def test_parse_basic_auth_header_invalid_base64(self):
        creds = _parse_basic_auth_header("Basic !!!notbase64!!!")
        self.assertIsNone(creds)

    def test_parse_basic_auth_header_missing_colon(self):
        token = base64.b64encode(b"userpass").decode("ascii")
        creds = _parse_basic_auth_header(f"Basic {token}")
        self.assertIsNone(creds)
