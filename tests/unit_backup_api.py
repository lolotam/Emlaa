# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import app_web  # noqa: E402
import backup  # noqa: E402
import core  # noqa: E402


class _Ctrl:
    engine = None
    window = None

    def __init__(self):
        self.dialogs = []

    def create_file_dialog(self, *args, **kwargs):
        self.dialogs.append(kwargs)
        return self.next_dialog


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.patches = [
            mock.patch.object(core, "BASE", self.base),
            mock.patch.object(backup, "reload_app", return_value={}),
        ]
        for p in self.patches:
            p.start()
        self.ctrl = mock.Mock()
        self.ctrl.engine = None
        self.ctrl.window = mock.Mock()
        self.api = app_web.Api(self.ctrl)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_cancel_writes_nothing(self):
        self.ctrl.window.create_file_dialog.return_value = None
        r = self.api.backup_export()
        self.assertEqual(r, {"ok": False, "err": ""})
        self.assertEqual(os.listdir(self.base), [])

    def test_good_zip_restores(self):
        os.makedirs(os.path.join(self.base, "recordings"))
        with open(os.path.join(self.base, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"lang": "ar"}, f)
        blob = backup.export_snapshot(self.base)
        other = os.path.join(self.base, "in.zip")
        with open(other, "wb") as f:
            f.write(blob)
        fresh = tempfile.mkdtemp()
        self.ctrl.window.create_file_dialog.return_value = other
        with mock.patch.object(core, "BASE", fresh), mock.patch.object(self.api, "bootstrap", return_value={"ok": 1}):
            r = self.api.backup_import()
        self.assertTrue(r["ok"])
        with open(os.path.join(fresh, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")

    def test_damaged_zip_leaves_directory(self):
        with open(os.path.join(self.base, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"lang": "ar"}')
        bad = os.path.join(self.base, "bad.zip")
        with open(bad, "wb") as f:
            f.write(b"not a zip")
        self.ctrl.window.create_file_dialog.return_value = bad
        with mock.patch.object(self.api, "bootstrap", return_value={}):
            r = self.api.backup_import()
        self.assertFalse(r["ok"])
        self.assertIn("مش نسخة", r["err"])
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")

    def test_busy_returns_wait_sentence(self):
        app = mock.Mock(recording=True, busy=False, capturing=False, backing_up=False)
        app._state_lock = core._backup_lock
        self.ctrl.engine = app
        r = self.api.backup_export()
        self.assertFalse(r["ok"])
        self.assertIn("استنى", r["err"])
        self.ctrl.window.create_file_dialog.assert_not_called()

    def test_status_hides_tokens_and_unconfigured_sign_in(self):
        status = self.api.backup_status()
        self.assertFalse(status["clientConfigured"])
        self.assertFalse(status["signedIn"])
        self.assertNotIn("refreshToken", status)
        r = self.api.google_sign_in()
        self.assertFalse(r["ok"])
        self.assertIn("مش متفعّل", r["err"])

    def test_ui_strings_have_english(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(root, "source", "ui", "index.html"), encoding="utf-8").read()
        i18n = open(os.path.join(root, "source", "ui", "i18n.js"), encoding="utf-8").read()
        needed = [
            "نسخة احتياطية",
            "الملف فيه مفاتيح الـAPI والسجل والحافظة وتسجيلات الصوت. خليه عندك وما تبعتهوش لحد.",
            "تنزيل نسخة احتياطية",
            "استعادة من ملف",
            "تسجيل الدخول بجوجل",
            "انسخ دلوقتي",
            "استرجع من Drive",
        ]
        for text in needed:
            self.assertIn(text, html)
            self.assertIn(text, i18n)
