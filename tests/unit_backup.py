# -*- coding: utf-8 -*-
"""صيغة النسخة واسترجاعها على مجلد مؤقت — من غير ملفات المستخدم الحقيقية."""
import json
import os
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import backup  # noqa: E402
import core  # noqa: E402
import providers  # noqa: E402


NOW = "2026-10-26T12:00:00Z"


def _zip(config=None, keys=None, history=None, clipboard=None, recordings=None):
    return backup.build_zip(
        {} if config is None else config,
        {} if keys is None else keys,
        [] if history is None else history,
        [] if clipboard is None else clipboard,
        {} if recordings is None else recordings,
        NOW,
    )


class FormatTests(unittest.TestCase):
    def test_round_trip_bytes(self):
        blob = _zip({"lang": "ar"}, {"groq": ["gsk_a"]}, [{"id": 1}], [{"t": "x"}],
                    {"1.mp3": b"mp3", "2.wav": b"wav", "2.json": b"{}"})
        got = backup.read_zip(blob)
        self.assertEqual(got["config"]["lang"], "ar")
        self.assertEqual(got["keys"]["groq"], ["gsk_a"])
        self.assertEqual(got["files"]["1.mp3"], b"mp3")
        self.assertEqual(got["recordings"], ["1.mp3", "2.json", "2.wav"])

    def test_rejects(self):
        good = json.loads(zipfile.ZipFile(BytesIO(_zip())).read("manifest.json"))

        def pack(manifest, members=None):
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("manifest.json", json.dumps(manifest).encode())
                for name, body in (members or {}).items():
                    zf.writestr(name, body)
            return buf.getvalue()

        cases = [
            ("format", dict(good, format="other"), "damaged"),
            ("version-true", dict(good, version=True), "damaged"),
            ("version-str", dict(good, version="1"), "damaged"),
            ("version-2", dict(good, version=2), "newer"),
            ("version-0", dict(good, version=0), "damaged"),
            ("missing", {k: v for k, v in good.items() if k != "keys"}, "damaged"),
            ("keys-str", dict(good, keys={"groq": "gsk_a"}), "damaged"),
            ("unknown-provider", dict(good, keys={"nope": ["x"]}), "damaged"),
            ("config-list", dict(good, config=[]), "damaged"),
            ("history-obj", dict(good, history={}), "damaged"),
            ("unsorted", dict(good, recordings=["2.mp3", "1.mp3"]), "damaged"),
        ]
        for name, manifest, code in cases:
            with self.subTest(name):
                with self.assertRaises(backup.BackupError) as cm:
                    backup.read_zip(pack(manifest))
                self.assertEqual(cm.exception.code, code)

        with self.assertRaises(backup.BackupError) as cm:
            backup.read_zip(pack(dict(good, recordings=["1.mp3"]), {"recordings/../1.mp3": b"x"}))
        self.assertEqual(cm.exception.code, "damaged")

        with self.assertRaises(backup.BackupError) as cm:
            backup.read_zip(pack(dict(good, recordings=["1.mp3"]), {"recordings/1.mp3": b"x", "notes.txt": b"n"}))
        self.assertEqual(cm.exception.code, "damaged")

        huge = dict(good)
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("manifest.json")
            zf.writestr(info, json.dumps(huge).encode())
            big = zipfile.ZipInfo("recordings/1.mp3")
            big.file_size = backup.MAX_ONE + 1
            zf.writestr(big, b"")
        # writestr يظبط file_size على طول المحتوى، فبنعدّل الحد في الفحص مباشرة
        with mock.patch.object(backup, "MAX_ONE", 1):
            with self.assertRaises(backup.BackupError) as cm:
                backup.read_zip(_zip(recordings={"1.mp3": b"abcd"}))
            self.assertEqual(cm.exception.code, "too_large")
            self.assertEqual(backup.message_for("too_large"), backup.message_for("damaged"))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.reload = mock.patch.object(backup, "reload_app", return_value={})
        self.reload.start()

    def tearDown(self):
        self.reload.stop()
        self.tmp.cleanup()

    def _write(self):
        os.makedirs(os.path.join(self.base, "recordings"))
        with open(os.path.join(self.base, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"lang": "ar", "dictionary": ["إملاء"]}, f)
        with open(os.path.join(self.base, ".env"), "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY = old\n")
            f.write("OTHER=keep\n")
            f.write("OPENAI_API_KEY=sk-1\n")
            f.write("ANTHROPIC_API_KEY=sk-ant-1\n")
            f.write("AI_GATEWAY_API_KEY=v-key\n")
        with open(os.path.join(self.base, "history.json"), "w", encoding="utf-8") as f:
            json.dump([{"id": 1, "raw": "أ"}], f)
        with open(os.path.join(self.base, "clipboard.json"), "w", encoding="utf-8") as f:
            json.dump([{"t": "نسخ"}], f)
        for name, body in (("1.mp3", b"a"), ("9.wav", b"b"), ("notes.txt", b"leave")):
            with open(os.path.join(self.base, "recordings", name), "wb") as f:
                f.write(body)

    def test_round_trip_directory(self):
        self._write()
        blob = backup.export_snapshot(self.base)
        fresh = tempfile.TemporaryDirectory()
        try:
            os.makedirs(os.path.join(fresh.name, "recordings"))
            with open(os.path.join(fresh.name, "recordings", "8.wav"), "wb") as f:
                f.write(b"local-only")
            with open(os.path.join(fresh.name, "recordings", "notes.txt"), "wb") as f:
                f.write(b"leave")
            with open(os.path.join(fresh.name, ".env"), "w", encoding="utf-8") as f:
                f.write("GEMINI_API_KEY=keep-me-not\nOTHER=stay\n")
            backup.restore_snapshot(fresh.name, blob)
            with open(os.path.join(fresh.name, "config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["lang"], "ar")
            with open(os.path.join(fresh.name, "history.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)[0]["raw"], "أ")
            env = open(os.path.join(fresh.name, ".env"), encoding="utf-8").read()
            self.assertIn("OTHER=stay", env)
            self.assertIn("GROQ_API_KEY=old", env)
            self.assertIn("OPENAI_API_KEY=sk-1", env)
            self.assertIn("ANTHROPIC_API_KEY=sk-ant-1", env)
            self.assertIn("AI_GATEWAY_API_KEY=v-key", env)
            self.assertNotIn("GEMINI", env)
            rec = os.path.join(fresh.name, "recordings")
            self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
            self.assertEqual(open(os.path.join(rec, "9.wav"), "rb").read(), b"b")
            self.assertFalse(os.path.exists(os.path.join(rec, "8.wav")))
            self.assertEqual(open(os.path.join(rec, "notes.txt"), "rb").read(), b"leave")
        finally:
            fresh.cleanup()
        backup.reload_app.assert_called_once()

    def test_unreadable_env_does_not_export(self):
        with open(os.path.join(self.base, ".env"), "wb") as f:
            f.write(b"\xff")
        with self.assertRaises(backup.BackupError) as cm:
            backup.export_snapshot(self.base)
        self.assertEqual(cm.exception.code, "unreadable")

    def test_history_replace_failure_rolls_back_documents_only(self):
        self._write()
        blob = _zip({"lang": "en"}, {})
        real = backup._atomic_json

        def boom(path, obj):
            if path.endswith("history.json"):
                raise OSError("disk")
            real(path, obj)

        with mock.patch.object(backup, "_atomic_json", side_effect=boom):
            with self.assertRaises(OSError):
                backup.restore_snapshot(self.base, blob)
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")
        self.assertTrue(os.path.exists(os.path.join(self.base, "recordings", "1.mp3")))
        backup.reload_app.assert_not_called()

    def test_recording_failure_restores_deleted_and_drops_new(self):
        self._write()
        blob = _zip(recordings={"3.mp3": b"new"})
        real_replace = os.replace
        calls = {"n": 0}

        def boom(src, dst):
            calls["n"] += 1
            if str(dst).endswith("3.mp3"):
                raise OSError("full")
            real_replace(src, dst)

        with mock.patch("backup.os.replace", side_effect=boom):
            with self.assertRaises(OSError):
                backup.restore_snapshot(self.base, blob)
        rec = os.path.join(self.base, "recordings")
        self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
        self.assertEqual(open(os.path.join(rec, "9.wav"), "rb").read(), b"b")
        self.assertFalse(os.path.exists(os.path.join(rec, "3.mp3")))

    def test_busy_before_any_write(self):
        self._write()
        app = mock.Mock(recording=True, busy=False, capturing=False, backing_up=False)
        app._state_lock = core._backup_lock
        before = open(os.path.join(self.base, "config.json"), encoding="utf-8").read()
        with self.assertRaises(backup.BackupError) as cm:
            backup.export_snapshot(self.base, app)
        self.assertEqual(cm.exception.code, "busy")
        self.assertEqual(open(os.path.join(self.base, "config.json"), encoding="utf-8").read(), before)

    def test_env_not_published_when_restore_fails(self):
        self._write()
        os.environ["GROQ_API_KEY"] = "still-here"
        blob = _zip(keys={"openai": ["sk-new"]})
        with mock.patch.object(backup, "_atomic_json", side_effect=OSError("no")):
            with self.assertRaises(OSError):
                backup.restore_snapshot(self.base, blob)
        self.assertEqual(os.environ.get("GROQ_API_KEY"), "still-here")


class ReloadTests(unittest.TestCase):
    def test_reload_updates_classic_cfg_and_restarts_hotkey(self):
        app = mock.Mock()
        app.cfg = {"lang": "en"}
        saved = dict(core.CFG)
        try:
            with mock.patch.object(core, "load_config", return_value={"lang": "ar"}):
                out = backup.reload_app(app)
            self.assertEqual(out["lang"], "ar")
            self.assertEqual(app.cfg["lang"], "ar")
            app.restart_hotkey.assert_called_once()
        finally:
            core.CFG.clear()
            core.CFG.update(saved)
