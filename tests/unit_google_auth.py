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

    def _sign_in(self, token, client_id):
        held = {}

        def opener(url):
            from urllib.parse import parse_qs, urlparse
            held["state"] = parse_qs(urlparse(url).query)["state"][0]

        def listener():
            def wait():
                return "http://127.0.0.1/cb?state=%s&code=abc" % held["state"]
            return "http://127.0.0.1/cb", wait

        def transport(method, url, headers, body):
            return 200, {}, json.dumps(token).encode()

        return google_auth.sign_in(client_id, transport, listener, opener, lambda: 1000, self.base)

    def _token(self, email, refresh=None, client_id="fake-client"):
        token = {
            "id_token": jwt({
                "aud": client_id,
                "iss": "accounts.google.com",
                "exp": 9999,
                "email": email,
                "name": email,
            }),
            "access_token": "at",
            "expires_in": 3600,
        }
        if refresh is not None:
            token["refresh_token"] = refresh
        return token

    def test_source_client_id_stays_empty(self):
        with open(google_auth.__file__, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('GOOGLE_CLIENT_ID = ""', text)
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")

    def test_other_account_without_refresh_token_drops_old_token_and_ids(self):
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")
        google_auth.write_state(self.base, {
            "account": {"email": "old@b.c", "name": "Old"},
            "refreshToken": "old-refresh",
            "folderId": "fold",
            "fileId": "file",
        })
        self._sign_in(self._token("new@b.c"), "fake-client")
        state = google_auth.read_state(self.base)
        self.assertEqual(state["account"]["email"], "new@b.c")
        self.assertNotIn("refreshToken", state)
        self.assertNotIn("folderId", state)
        self.assertNotIn("fileId", state)
        with open(google_auth.state_path(self.base), encoding="utf-8") as handle:
            self.assertNotIn("old-refresh", handle.read())
        self.assertEqual(google_auth.GOOGLE_CLIENT_ID, "")

    def test_other_account_with_new_refresh_token_clears_ids(self):
        google_auth.write_state(self.base, {
            "account": {"email": "old@b.c"},
            "refreshToken": "old-refresh",
            "folderId": "fold",
            "fileId": "file",
        })
        self._sign_in(self._token("new@b.c", refresh="new-refresh"), "fake-client")
        state = google_auth.read_state(self.base)
        self.assertEqual(state["refreshToken"], "new-refresh")
        self.assertNotIn("folderId", state)
        self.assertNotIn("fileId", state)
        with open(google_auth.state_path(self.base), encoding="utf-8") as handle:
            self.assertNotIn("old-refresh", handle.read())

    def test_same_account_without_refresh_token_keeps_previous(self):
        google_auth.write_state(self.base, {
            "account": {"email": "same@b.c"},
            "refreshToken": "keep-refresh",
            "folderId": "fold",
            "fileId": "file",
        })
        self._sign_in(self._token("same@b.c"), "fake-client")
        state = google_auth.read_state(self.base)
        self.assertEqual(state["refreshToken"], "keep-refresh")
        self.assertEqual(state["folderId"], "fold")
        self.assertEqual(state["fileId"], "file")

    def test_urllib_transport_stops_at_the_read_cap(self):
        payload = b"x" * 40

        class Body:
            def __init__(self):
                self.sizes = []
                self.status = 200
                self.headers = {}

            def read(self, n=-1):
                self.sizes.append(n)
                if n is None or n < 0:
                    return payload
                return payload[:n]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        body = Body()
        with mock.patch.object(google_auth, "BACKUP_READ_CAP", 10), \
             mock.patch.object(google_auth, "providers_ssl", return_value=None), \
             mock.patch("urllib.request.urlopen", return_value=body):
            status, _headers, got = google_auth.urllib_transport("GET", "https://example.test/file", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(body.sizes, [11])
        self.assertEqual(got, b"x" * 11)
