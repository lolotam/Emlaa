# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import backup  # noqa: E402
import drive_backup  # noqa: E402
import google_auth  # noqa: E402


class Script:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if not self.replies:
            raise AssertionError("no reply for " + method + " " + url)
        return self.replies.pop(0)


def ok(obj, status=200, headers=None):
    return status, headers or {}, json.dumps(obj).encode()


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.reload = mock.patch.object(backup, "reload_app", return_value={})
        self.reload.start()

    def tearDown(self):
        self.reload.stop()
        self.tmp.cleanup()

    def test_failed_upload_keeps_old_id(self):
        google_auth.write_state(self.base, {"folderId": "fold", "fileId": "old", "account": {"email": "a@b.c"}})
        script = Script([
            ok({"id": "fold", "trashed": False}),
            (200, {"Location": "http://upload"}, b"{}"),
            (500, {}, b"{}"),
        ])
        with self.assertRaises(backup.BackupError):
            drive_backup.upload(self.base, b"zip", script, "tok", 10)
        self.assertEqual(google_auth.read_state(self.base)["fileId"], "old")

    def test_rename_then_failed_delete_keeps_new_id(self):
        google_auth.write_state(self.base, {"folderId": "fold", "fileId": "old"})
        script = Script([
            ok({"id": "fold", "trashed": False}),
            (200, {"Location": "http://upload"}, b"{}"),
            ok({"id": "incoming"}),
            ok({"id": "new"}),
            (500, {}, b"{}"),  # delete old
            ok({"files": []}),
        ])
        got = drive_backup.upload(self.base, b"zip", script, "tok", 22)
        self.assertEqual(got["fileId"], "new")
        self.assertEqual(google_auth.read_state(self.base)["fileId"], "new")

    def test_stale_id_downloads_name_match(self):
        google_auth.write_state(self.base, {"folderId": "fold", "fileId": "stale"})
        script = Script([
            ok({"id": "fold", "trashed": False}),
            ok({"files": [{"id": "live", "name": "emlaa-backup.zip", "modifiedTime": "t"}]}),
            (200, {}, b"PK"),
        ])
        self.assertEqual(drive_backup.download(self.base, script, "tok"), b"PK")
        self.assertEqual(google_auth.read_state(self.base)["fileId"], "live")

    def test_empty_state_reuses_existing_folder(self):
        google_auth.write_state(self.base, {})
        script = Script([
            ok({"files": [{"id": "fold", "modifiedTime": "t"}]}),
            (200, {"Location": "http://upload"}, b"{}"),
            ok({"id": "incoming"}),
            ok({"id": "new"}),
            ok({"files": [{"id": "new"}]}),
        ])
        drive_backup.upload(self.base, b"zip", script, "tok", 1)
        posts = [url for method, url in script.calls if method == "POST" and "uploadType" not in url]
        self.assertEqual(posts, [])

    def test_missing_file_does_not_restore(self):
        google_auth.write_state(self.base, {"folderId": "fold"})
        script = Script([
            ok({"id": "fold", "trashed": False}),
            ok({"files": []}),
        ])
        with mock.patch.object(backup, "restore_snapshot") as restore:
            with self.assertRaises(backup.BackupError) as cm:
                drive_backup.restore(self.base, script, "tok")
            self.assertEqual(cm.exception.code, "no_drive_file")
            restore.assert_not_called()

    def test_upload_after_sign_out_does_not_restore_refresh_token(self):
        google_auth.write_state(self.base, {
            "folderId": "fold",
            "fileId": "old",
            "account": {"email": "a@b.c"},
            "refreshToken": "secret-refresh",
        })

        class Transport:
            def __call__(self, method, url, headers, body):
                if method == "GET" and "/files/fold" in url:
                    return ok({"id": "fold", "trashed": False})
                if method == "POST":
                    return (200, {"Location": "http://upload.example/session"}, b"{}")
                if method == "PUT":
                    google_auth.sign_out(self_base)
                    return ok({"id": "incoming"})
                if method == "PATCH":
                    return ok({"id": "new"})
                if method == "DELETE":
                    return (204, {}, b"")
                if method == "GET":
                    return ok({"files": []})
                raise AssertionError(method + " " + url)

        self_base = self.base
        got = drive_backup.upload(self.base, b"zip", Transport(), "tok", 22)
        self.assertEqual(got["fileId"], "new")
        self.assertFalse(os.path.exists(google_auth.state_path(self.base)))
        for name in os.listdir(self.base):
            with open(os.path.join(self.base, name), "rb") as handle:
                self.assertNotIn(b"secret-refresh", handle.read())

    def test_finished_upload_keeps_refresh_token_while_signed_in(self):
        google_auth.write_state(self.base, {
            "folderId": "fold",
            "fileId": "old",
            "refreshToken": "keep-me",
            "account": {"email": "a@b.c"},
        })
        script = Script([
            ok({"id": "fold", "trashed": False}),
            (200, {"Location": "http://upload"}, b"{}"),
            ok({"id": "incoming"}),
            ok({"id": "new"}),
            (204, {}, b""),
            ok({"files": []}),
        ])
        drive_backup.upload(self.base, b"zip", script, "tok", 22)
        self.assertEqual(google_auth.read_state(self.base)["refreshToken"], "keep-me")

    def test_oversized_download_does_not_restore(self):
        google_auth.write_state(self.base, {"folderId": "fold", "refreshToken": "keep-me"})
        script = Script([
            ok({"id": "fold", "trashed": False}),
            ok({"files": [{"id": "live", "name": "emlaa-backup.zip"}]}),
            (200, {}, b"x" * 40),
        ])
        with mock.patch.object(google_auth, "BACKUP_READ_CAP", 16), \
             mock.patch.object(backup, "restore_snapshot") as restore:
            with self.assertRaises(backup.BackupError) as cm:
                drive_backup.restore(self.base, script, "tok")
            self.assertEqual(cm.exception.code, "too_large")
            self.assertEqual(backup.message_for(cm.exception.code), backup.MESSAGES["damaged"])
            restore.assert_not_called()
        self.assertEqual(google_auth.read_state(self.base).get("refreshToken"), "keep-me")
