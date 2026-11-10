# -*- coding: utf-8 -*-
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import backup  # noqa: E402
import google_auth  # noqa: E402


def jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "h." + body + ".s"


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        google_auth.forget_for_tests(self.base)

    def tearDown(self):
        google_auth.forget_for_tests(self.base)
        self.tmp.cleanup()

    def test_empty_client_id_calls_nothing(self):
        def boom(*a, **k):
            raise AssertionError("called")
        with self.assertRaises(backup.BackupError) as cm:
            google_auth.sign_in("", boom, boom, boom, boom, self.base)
        self.assertEqual(cm.exception.code, "unconfigured")
        self.assertFalse(os.path.exists(google_auth.state_path(self.base)))

    def test_bad_state_writes_nothing(self):
        calls = []

        def listener():
            return "http://127.0.0.1/cb", lambda: "http://127.0.0.1/cb?state=nope&code=abc"

        def opener(url):
            calls.append(url)

        def transport(*a):
            raise AssertionError("token")

        with self.assertRaises(backup.BackupError):
            google_auth.sign_in("client", transport, listener, opener, lambda: 1000, self.base)
        self.assertTrue(calls)
        self.assertFalse(os.path.exists(google_auth.state_path(self.base)))

    def test_sign_out_removes_file_without_transport(self):
        google_auth.write_state(self.base, {"account": {"email": "a@b.c"}, "refreshToken": "r"})

        def transport(*a):
            raise AssertionError("network")

        google_auth.sign_out(self.base, transport)
        self.assertFalse(os.path.exists(google_auth.state_path(self.base)))

    def test_audience_mismatch_writes_nothing(self):
        token = {"id_token": jwt({"aud": "other", "iss": "accounts.google.com", "exp": 9999, "email": "a@b.c"}),
                 "access_token": "at", "refresh_token": "rt", "expires_in": 3600}

        def listener():
            return "http://127.0.0.1/cb", lambda: "http://127.0.0.1/cb?state=STATE&code=abc"

        state = {}

        def opener(url):
            from urllib.parse import parse_qs, urlparse
            state["s"] = parse_qs(urlparse(url).query)["state"][0]

        def wait_factory():
            uri, _wait = listener()

            def wait():
                return "http://127.0.0.1/cb?state=%s&code=abc" % state["s"]
            return uri, wait

        def transport(method, url, headers, body):
            return 200, {}, json.dumps(token).encode()

        with self.assertRaises(backup.BackupError) as cm:
            google_auth.sign_in("client", transport, wait_factory, opener, lambda: 1000, self.base)
        self.assertEqual(cm.exception.code, "reauth")
        self.assertFalse(os.path.exists(google_auth.state_path(self.base)))
