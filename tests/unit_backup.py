# -*- coding: utf-8 -*-
"""صيغة النسخة واسترجاعها على مجلد مؤقت — من غير ملفات المستخدم الحقيقية."""
import json
import os
import shutil
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


def _flip_central_crc(blob):
    data = bytearray(blob)
    start = 0
    found = 0
    while True:
        idx = data.find(b"PK\x01\x02", start)
        if idx < 0:
            break
        data[idx + 16] ^= 0xFF
        found += 1
        start = idx + 4
    if not found:
        raise AssertionError("central directory missing")
    return bytes(data)


def _cd_index(data, member):
    encoded = member.encode("utf-8")
    idx = 0
    while True:
        idx = data.find(b"PK\x01\x02", idx)
        if idx < 0:
            raise AssertionError(member)
        namelen = int.from_bytes(data[idx + 28:idx + 30], "little")
        if bytes(data[idx + 46:idx + 46 + namelen]) == encoded:
            return idx
        idx += 4


def _stored_backup():
    manifest = json.dumps({
        "format": "emlaa-backup",
        "version": 1,
        "exportedAt": NOW,
        "config": {},
        "keys": {},
        "history": [],
        "clipboard": [],
        "recordings": ["1.mp3"],
    }).encode("utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", manifest)
        zf.writestr("recordings/1.mp3", b"hello-audio")
    return buf.getvalue()


def _truncated_member(blob):
    data = bytearray(blob)
    man = _cd_index(data, "manifest.json")
    rec = _cd_index(data, "recordings/1.mp3")
    data[man + 20:man + 24] = (100_000).to_bytes(4, "little")
    data[man + 24:man + 28] = (100_000).to_bytes(4, "little")
    data[rec + 42:rec + 46] = (0x0FFFFFFF).to_bytes(4, "little")
    return bytes(data)


def _truncated_header(blob):
    data = bytearray(blob)
    rec = _cd_index(data, "recordings/1.mp3")
    data[rec + 42:rec + 46] = (0x0FFFFFFF).to_bytes(4, "little")
    return bytes(data)


def _flip_deflate_byte(blob):
    data = bytearray(blob)
    idx = data.find(b"PK\x03\x04")
    if idx < 0:
        raise AssertionError("local header missing")
    namelen = int.from_bytes(data[idx + 26:idx + 28], "little")
    extra = int.from_bytes(data[idx + 28:idx + 30], "little")
    comp = int.from_bytes(data[idx + 18:idx + 22], "little")
    if comp < 1:
        raise AssertionError("no payload")
    data[idx + 30 + namelen + extra] ^= 0xFF
    return bytes(data)


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
        sample = _zip(recordings={"1.mp3": b"abcd"})
        with mock.patch.object(backup, "MAX_ONE", 1):
            with self.assertRaises(backup.BackupError) as cm:
                backup.read_zip(sample)
            self.assertEqual(cm.exception.code, "too_large")
            self.assertEqual(backup.message_for("too_large"), backup.message_for("damaged"))

    def test_build_zip_rejects_oversize_before_write(self):
        sample = _zip(recordings={"1.mp3": b"a", "2.wav": b"bb"})
        with zipfile.ZipFile(BytesIO(sample)) as zf:
            infos = {i.filename: i.file_size for i in zf.infolist()}
        manifest_size = infos["manifest.json"]
        biggest = max(infos.values())
        total = sum(infos.values())

        with self.subTest("members"):
            with mock.patch.object(backup.zipfile, "ZipFile") as opened, \
                 mock.patch.object(backup, "MAX_MEMBERS", 1):
                with self.assertRaises(backup.BackupError) as cm:
                    _zip(recordings={"1.mp3": b"a"})
                self.assertEqual(cm.exception.code, "too_large")
                opened.assert_not_called()

        with self.subTest("one"):
            payload = b"x" * (manifest_size + 30)
            with mock.patch.object(backup.zipfile, "ZipFile") as opened, \
                 mock.patch.object(backup, "MAX_ONE", manifest_size + 10):
                with self.assertRaises(backup.BackupError) as cm:
                    _zip(recordings={"1.mp3": payload})
                self.assertEqual(cm.exception.code, "too_large")
                opened.assert_not_called()

        with self.subTest("total"):
            with mock.patch.object(backup.zipfile, "ZipFile") as opened, \
                 mock.patch.object(backup, "MAX_ONE", biggest), \
                 mock.patch.object(backup, "MAX_TOTAL", total - 1):
                with self.assertRaises(backup.BackupError) as cm:
                    _zip(recordings={"1.mp3": b"a", "2.wav": b"bb"})
                self.assertEqual(cm.exception.code, "too_large")
                opened.assert_not_called()

        self.assertEqual(backup.message_for("too_large"), backup.message_for("damaged"))

    def test_zip_errors_are_damaged(self):
        good = _zip(recordings={"1.mp3": b"hello-audio-payload"})
        stored = _stored_backup()
        cases = {
            "crc": _flip_central_crc(good),
            "deflate": _flip_deflate_byte(good),
            "truncated-member": _truncated_member(stored),
            "truncated-header": _truncated_header(stored),
            "garbage": b"this is not a zip",
            "tail": good[:-20],
        }
        for name, blob in cases.items():
            with self.subTest(name):
                with self.assertRaises(backup.BackupError) as cm:
                    backup.read_zip(blob)
                self.assertEqual(cm.exception.code, "damaged")
                self.assertNotIsInstance(cm.exception, zipfile.BadZipFile)

    def test_other_compression_is_damaged(self):
        good = json.loads(zipfile.ZipFile(BytesIO(_zip())).read("manifest.json"))
        for method in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(method):
                buf = BytesIO()
                with zipfile.ZipFile(buf, "w", compression=method) as zf:
                    zf.writestr("manifest.json", json.dumps(good).encode("utf-8"))
                with self.assertRaises(backup.BackupError) as cm:
                    backup.read_zip(buf.getvalue())
                self.assertEqual(cm.exception.code, "damaged")


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
        journal = tempfile.mkdtemp(prefix="emlaa-restore-")
        live = os.path.join(self.base, "recordings", "7.wav")

        def boom(path, obj):
            if path.endswith("history.json"):
                with open(live, "wb") as f:
                    f.write(b"live")
                raise OSError("disk")
            real(path, obj)

        try:
            with mock.patch.object(backup, "_atomic_json", side_effect=boom), \
                 mock.patch.object(backup, "_rollback_recordings", wraps=backup._rollback_recordings) as recs, \
                 mock.patch("backup.tempfile.mkdtemp", return_value=journal):
                with self.assertRaises(OSError):
                    backup.restore_snapshot(self.base, blob)
            recs.assert_not_called()
            self.assertFalse(os.path.exists(journal))
        finally:
            shutil.rmtree(journal, ignore_errors=True)
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")
        self.assertEqual(open(os.path.join(self.base, "recordings", "1.mp3"), "rb").read(), b"a")
        self.assertEqual(open(live, "rb").read(), b"live")
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
        self.assertFalse(os.path.exists(os.path.join(rec, "3.mp3.incoming")))

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

    def test_export_refuses_recording_restore_would_reject(self):
        self._write()
        small = backup.export_snapshot(self.base)
        with zipfile.ZipFile(BytesIO(small)) as zf:
            manifest_size = zf.getinfo("manifest.json").file_size
        payload = b"x" * (manifest_size + 500)
        with open(os.path.join(self.base, "recordings", "1.mp3"), "wb") as f:
            f.write(payload)
        before = open(os.path.join(self.base, "config.json"), encoding="utf-8").read()
        with mock.patch.object(backup, "MAX_ONE", manifest_size + 100), \
             mock.patch.object(backup.zipfile, "ZipFile") as opened:
            with self.assertRaises(backup.BackupError) as cm:
                backup.export_snapshot(self.base)
            self.assertEqual(cm.exception.code, "too_large")
            opened.assert_not_called()
        self.assertEqual(backup.message_for("too_large"), backup.message_for("damaged"))
        self.assertEqual(open(os.path.join(self.base, "config.json"), encoding="utf-8").read(), before)
        self.assertEqual(open(os.path.join(self.base, "recordings", "1.mp3"), "rb").read(), payload)

    def test_damaged_zip_writes_nothing(self):
        self._write()
        before = open(os.path.join(self.base, "config.json"), encoding="utf-8").read()
        blob = _flip_central_crc(_zip(recordings={"1.mp3": b"hello-audio-payload"}))
        with mock.patch.object(backup, "_apply") as apply:
            with self.assertRaises(backup.BackupError) as cm:
                backup.restore_snapshot(self.base, blob)
        self.assertEqual(cm.exception.code, "damaged")
        apply.assert_not_called()
        self.assertEqual(open(os.path.join(self.base, "config.json"), encoding="utf-8").read(), before)
        self.assertEqual(open(os.path.join(self.base, "recordings", "1.mp3"), "rb").read(), b"a")

    def test_unstorable_key_rejected_before_write(self):
        self._write()
        before = open(os.path.join(self.base, "config.json"), encoding="utf-8").read()
        groq_before = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = "keep-real"
        try:
            for bad in ("ab\0cd", "abc\nOTHER=value", "abc\rset"):
                with self.subTest(bad):
                    good = json.loads(zipfile.ZipFile(BytesIO(_zip())).read("manifest.json"))
                    manifest = dict(good, config={"lang": "en"}, keys={"groq": [bad]})
                    buf = BytesIO()
                    with zipfile.ZipFile(buf, "w") as zf:
                        zf.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
                    with mock.patch.object(backup, "_apply") as apply:
                        with self.assertRaises(backup.BackupError) as cm:
                            backup.restore_snapshot(self.base, buf.getvalue())
                    self.assertEqual(cm.exception.code, "damaged")
                    apply.assert_not_called()
                    self.assertEqual(open(os.path.join(self.base, "config.json"), encoding="utf-8").read(), before)
                    self.assertEqual(os.environ.get("GROQ_API_KEY"), "keep-real")
                    with mock.patch.object(backup.zipfile, "ZipFile") as opened:
                        with self.assertRaises(backup.BackupError) as cm:
                            backup.build_zip({}, {"groq": [bad]}, [], [], {}, NOW)
                        self.assertEqual(cm.exception.code, "damaged")
                        opened.assert_not_called()
        finally:
            if groq_before is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = groq_before

    def test_makedirs_failure_puts_documents_back(self):
        self._write()
        blob = _zip({"lang": "en"}, {})
        target = os.path.abspath(os.path.join(self.base, "recordings"))
        real = os.makedirs

        def boom(path, mode=0o777, exist_ok=False):
            if os.path.abspath(path) == target:
                raise OSError("mkdir")
            return real(path, mode, exist_ok=exist_ok)

        journal = tempfile.mkdtemp(prefix="emlaa-restore-")
        try:
            with mock.patch("backup.os.makedirs", side_effect=boom), \
                 mock.patch("backup.tempfile.mkdtemp", return_value=journal):
                with self.assertRaises(OSError):
                    backup.restore_snapshot(self.base, blob)
            self.assertFalse(os.path.exists(journal))
        finally:
            shutil.rmtree(journal, ignore_errors=True)
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")
        env = open(os.path.join(self.base, ".env"), encoding="utf-8").read()
        self.assertIn("GROQ_API_KEY = old", env)
        rec = os.path.join(self.base, "recordings")
        self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
        self.assertEqual(open(os.path.join(rec, "notes.txt"), "rb").read(), b"leave")
        backup.reload_app.assert_not_called()

    def test_recording_not_deleted_if_journal_copy_fails(self):
        self._write()
        blob = _zip(recordings={"3.mp3": b"new"})
        real = backup._copy_aside

        def boom(path, folder, label):
            if str(label).endswith("1.mp3"):
                raise OSError("copy")
            return real(path, folder, label)

        with mock.patch.object(backup, "_copy_aside", side_effect=boom):
            with self.assertRaises(OSError):
                backup.restore_snapshot(self.base, blob)
        rec = os.path.join(self.base, "recordings")
        self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
        self.assertEqual(open(os.path.join(rec, "notes.txt"), "rb").read(), b"leave")
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")

    def test_failed_rollback_keeps_journal_and_still_restores_recordings(self):
        self._write()
        journal = tempfile.mkdtemp(prefix="emlaa-restore-")
        blob = _zip({"lang": "en"}, recordings={"3.mp3": b"zzz"})
        real_replace = os.replace
        real_copy = shutil.copy2

        def boom_replace(src, dst):
            if str(dst).endswith("3.mp3"):
                raise OSError("full")
            return real_replace(src, dst)

        def boom_copy(src, dst, *args, **kwargs):
            if "emlaa-restore-" in str(src):
                raise OSError("put back")
            return real_copy(src, dst, *args, **kwargs)

        try:
            with mock.patch("backup.tempfile.mkdtemp", return_value=journal), \
                 mock.patch("backup.os.replace", side_effect=boom_replace), \
                 mock.patch("backup.shutil.copy2", side_effect=boom_copy):
                with self.assertRaises(backup.BackupError) as cm:
                    backup.restore_snapshot(self.base, blob)
            self.assertEqual(cm.exception.code, "damaged")
            self.assertIn(journal, str(cm.exception))
            self.assertTrue(os.path.isdir(journal))
            self.assertTrue(getattr(cm.exception, "keep_journal", False))
            with open(os.path.join(journal, "config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["lang"], "ar")
            self.assertEqual(open(os.path.join(journal, "recordings", "1.mp3"), "rb").read(), b"a")
            rec = os.path.join(self.base, "recordings")
            self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
            self.assertEqual(open(os.path.join(rec, "9.wav"), "rb").read(), b"b")
            self.assertFalse(os.path.exists(os.path.join(rec, "3.mp3")))
            self.assertEqual(open(os.path.join(rec, "notes.txt"), "rb").read(), b"leave")
            with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["lang"], "en")
        finally:
            shutil.rmtree(journal, ignore_errors=True)

    def test_publish_failure_rolls_files_back(self):
        self._write()
        os.environ["GROQ_API_KEY"] = "still-here"
        blob = _zip({"lang": "en"}, {"openai": ["sk-new"]}, recordings={"3.mp3": b"new"})
        journal = tempfile.mkdtemp(prefix="emlaa-restore-")
        try:
            with mock.patch.object(backup, "_publish_env", side_effect=ValueError("env")), \
                 mock.patch("backup.tempfile.mkdtemp", return_value=journal):
                with self.assertRaises(ValueError):
                    backup.restore_snapshot(self.base, blob)
            self.assertFalse(os.path.exists(journal))
        finally:
            shutil.rmtree(journal, ignore_errors=True)
        with open(os.path.join(self.base, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lang"], "ar")
        env = open(os.path.join(self.base, ".env"), encoding="utf-8").read()
        self.assertIn("GROQ_API_KEY = old", env)
        self.assertNotIn("sk-new", env)
        rec = os.path.join(self.base, "recordings")
        self.assertEqual(open(os.path.join(rec, "1.mp3"), "rb").read(), b"a")
        self.assertEqual(open(os.path.join(rec, "9.wav"), "rb").read(), b"b")
        self.assertFalse(os.path.exists(os.path.join(rec, "3.mp3")))
        self.assertFalse(os.path.exists(os.path.join(rec, "3.mp3.incoming")))
        self.assertEqual(os.environ.get("GROQ_API_KEY"), "still-here")
        backup.reload_app.assert_not_called()

    def test_success_deletes_journal(self):
        self._write()
        journal = tempfile.mkdtemp(prefix="emlaa-restore-")
        try:
            with mock.patch("backup.tempfile.mkdtemp", return_value=journal):
                backup.restore_snapshot(self.base, _zip({"lang": "ar"}))
            self.assertFalse(os.path.exists(journal))
        finally:
            shutil.rmtree(journal, ignore_errors=True)


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
