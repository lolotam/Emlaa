# -*- coding: utf-8 -*-
"""
اختبارات Task 15 — التفريغ بدون إنترنت (source/offline.py) + NetworkError + is_network_error.
مفيش شبكة ولا مفاتيح ولا BASE الحقيقي: opener بيقدّم بايتات جاهزة، subprocess.run متزوّد
fake، وcore.BASE متغيّر لمجلد مؤقت — بنختبر القرار الفعلي مش الاستدعاءات.
"""
import os
import io
import sys
import json
import socket
import hashlib
import zipfile
import subprocess
import tempfile
import time
import threading
import unittest
import urllib.error
import http.client
from types import SimpleNamespace
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core        # noqa: E402
import smart       # noqa: E402
import providers   # noqa: E402
import offline     # noqa: E402


# ── أدوات مساعدة ──────────────────────────────────────────────────────────────
def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _make_zip(entries):
    """zip في الذاكرة من {اسم: بايتات} — للفك من غير شبكة."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def _wav(tmp):
    p = os.path.join(tmp, "t.wav")
    _write(p, b"RIFF-fake-WAVE")
    return p


class _FakeOpener:
    """بيرجّع بايتات معيّنة لكل URL — مكان الشبكة في الاختبارات."""

    def __init__(self, urls):
        self.urls = dict(urls)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.urls:
            raise urllib.error.URLError("مش لاقي " + url)
        return io.BytesIO(self.urls[url])


class _BaseCase(unittest.TestCase):
    """بيقفل core.BASE على مجلد مؤقت — عشان offline ميمسش BASE الحقيقي أبدًا."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._base = mock.patch.object(core, "BASE", self._tmp.name)
        self._base.start()
        # كاش الفحص على مستوى الموديول ومفتاحه (mtime_ns, size) — من غير المسح
        # نتيجة اختبار ممكن تعدّي لاختبار تاني مانيڨسته بنفس الحجم
        offline._verify_cache.clear()
        self.addCleanup(offline._verify_cache.clear)

    def tearDown(self):
        self._base.stop()
        self._tmp.cleanup()

    def _install(self, model="base"):
        """بيجهّز تثبيت سليم (manifest + bin + model) جوه الـBASE المؤقت."""
        root = os.path.join(self._tmp.name, "offline")
        bin_dir = os.path.join(root, "bin")
        model_dir = os.path.join(root, "models")
        os.makedirs(bin_dir); os.makedirs(model_dir)
        exe = b"EXE"
        model_data = b"MODEL"
        _write(os.path.join(bin_dir, "whisper-cli.exe"), exe)
        _write(os.path.join(model_dir, model + ".bin"), model_data)
        # T20: بنكتب خريطة بصمات صحيحة عشان verify()/transcribe() يعدّوا من غير
        # ما يعتمدوا على بصمة الموديل الحقيقية (المحتوى هنا وهمي).
        manifest = {"model": model, "version": offline.WHISPER_CPP_VERSION,
                    "files": {"bin/whisper-cli.exe": len(exe), "models/" + model + ".bin": len(model_data)},
                    "sha256": {"bin/whisper-cli.exe": _sha256(exe), "models/" + model + ".bin": _sha256(model_data)}}
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        return root


# ── installed() ───────────────────────────────────────────────────────────────
class TestInstalled(_BaseCase):
    def test_none_without_manifest(self):
        self.assertIsNone(offline.installed())

    def test_returns_model_when_complete(self):
        self._install("base")
        self.assertEqual(offline.installed(), "base")

    def test_none_when_file_missing(self):
        root = self._install("base")
        os.remove(os.path.join(root, "models", "base.bin"))
        self.assertIsNone(offline.installed())

    def test_none_when_size_mismatch(self):
        root = self._install("base")
        # بنكتب حاجة أكبر من الحجم المسجّل في المانيڨست (5)
        _write(os.path.join(root, "models", "base.bin"), b"BIGGER")
        self.assertIsNone(offline.installed())

    def test_none_when_manifest_corrupt(self):
        root = os.path.join(self._tmp.name, "offline")
        os.makedirs(root)
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(offline.installed())


# ── build_cmd() ───────────────────────────────────────────────────────────────
class TestBuildCmd(_BaseCase):
    def test_arabic_language(self):
        cmd = offline.build_cmd("w.wav", "m.bin", "ar", "out")
        self.assertEqual(cmd[cmd.index("-l") + 1], "ar")

    def test_auto_when_no_language(self):
        cmd = offline.build_cmd("w.wav", "m.bin", None, "out")
        self.assertEqual(cmd[cmd.index("-l") + 1], "auto")

    def test_exe_from_bin_dir_and_args(self):
        cmd = offline.build_cmd("w.wav", "m.bin", "ar", "out")
        self.assertEqual(cmd[0], os.path.join(core.BASE, "offline", "bin", "whisper-cli.exe"))
        self.assertIn("-nt", cmd)
        self.assertIn("-otxt", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "m.bin")
        self.assertEqual(cmd[cmd.index("-f") + 1], "w.wav")
        self.assertEqual(cmd[cmd.index("-of") + 1], "out")


# ── _stream_download() ────────────────────────────────────────────────────────
class TestStreamDownload(_BaseCase):
    def test_writes_file_and_removes_part(self):
        data = b"PAYLOAD"
        dest = os.path.join(self._tmp.name, "f.bin")
        with mock.patch.object(offline, "_opener",
                               _FakeOpener({"https://x/y": data})):
            offline._stream_download("https://x/y", dest, _sha256(data), len(data),
                                     None, 0, len(data))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_sha_mismatch_raises(self):
        data = b"PAYLOAD"
        dest = os.path.join(self._tmp.name, "f.bin")
        with mock.patch.object(offline, "_opener",
                               _FakeOpener({"https://x/y": data})):
            with self.assertRaises(RuntimeError):
                offline._stream_download("https://x/y", dest, _sha256(b"OTHER"),
                                         len(data), None, 0, len(data))

    def test_size_mismatch_raises(self):
        data = b"PAYLOAD"
        dest = os.path.join(self._tmp.name, "f.bin")
        with mock.patch.object(offline, "_opener",
                               _FakeOpener({"https://x/y": data})):
            with self.assertRaises(RuntimeError):
                offline._stream_download("https://x/y", dest, _sha256(data),
                                         len(data) + 100, None, 0, len(data) + 100)


# ── _extract_bin() ────────────────────────────────────────────────────────────
class TestExtractBin(_BaseCase):
    def _run_extract(self, entries, dest):
        path = os.path.join(self._tmp.name, "a.zip")
        _write(path, _make_zip(entries))
        offline._extract_bin(path, dest)

    def test_keeps_exe_and_dlls_only(self):
        entries = {
            "Release/whisper-cli.exe": b"EXE",
            "Release/ggml.dll": b"GGML",
            "Release/SDL2.dll": b"SKIP-SDL",
            "Release/parakeet.dll": b"SKIP-PARA",
            "Release/parakeet-extra.dll": b"SKIP-PARA2",
            "README.md": b"skip-non-release",
        }
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest)
        self._run_extract(entries, dest)
        names = sorted(os.listdir(dest))
        self.assertEqual(names, ["ggml.dll", "whisper-cli.exe"])

    def test_rejects_dotdot_archive(self):
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest)
        with self.assertRaises(RuntimeError):
            self._run_extract({"Release/../evil.exe": b"x"}, dest)

    def test_rejects_absolute_path_archive(self):
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest)
        abs_name = os.path.abspath("evil.exe")
        with self.assertRaises(RuntimeError):
            self._run_extract({abs_name: b"x"}, dest)

    def test_rejects_drive_path_after_release(self):
        # N3: "Release/C:/x.dll" — بعد قصّ "Release/" بيفضل "C:/x.dll" فيه ":"
        # و"/" — لازم يترفض قبل ما يتكتب أي حاجة
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest)
        with self.assertRaises(RuntimeError):
            self._run_extract({"Release/C:/x.dll": b"x"}, dest)
        self.assertEqual(os.listdir(dest), [])

    def test_rejects_backslash_path_after_release(self):
        # N3: "Release/a\\b.dll" — فاصل مسار ويندوز مخفّي بعد "Release/"
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest)
        with self.assertRaises(RuntimeError):
            self._run_extract({"Release/a\\b.dll": b"x"}, dest)
        self.assertEqual(os.listdir(dest), [])


# ── download() ────────────────────────────────────────────────────────────────
MODEL_URL = "https://example.com/model.bin"
ZIP_URL = "https://example.com/whisper.zip"
MODEL_BYTES = b"FAKE-MODEL"
ZIP_BYTES = _make_zip({
    "Release/whisper-cli.exe": b"EXE",
    "Release/ggml.dll": b"GGML",
    "Release/SDL2.dll": b"SKIP",
    "Release/parakeet.dll": b"SKIP",
})


def _download_patches():
    """كل الـpatches اللي download محتاجها عشان يشتغل من غير شبكة."""
    return (
        mock.patch.object(offline, "MODELS",
                          {"test-model": (MODEL_URL, _sha256(MODEL_BYTES), len(MODEL_BYTES))}),
        mock.patch.object(offline, "WHISPER_CPP_URL", ZIP_URL),
        mock.patch.object(offline, "WHISPER_CPP_SHA256", _sha256(ZIP_BYTES)),
        mock.patch.object(offline, "WHISPER_CPP_SIZE", len(ZIP_BYTES)),
        mock.patch.object(offline, "_opener",
                          _FakeOpener({MODEL_URL: MODEL_BYTES, ZIP_URL: ZIP_BYTES})),
        mock.patch.object(offline, "_run", return_value=SimpleNamespace(returncode=0)),
    )


class TestDownload(_BaseCase):
    def test_installs_and_writes_manifest_last(self):
        p1, p2, p3, p4, p5, p6 = _download_patches()
        with p1, p2, p3, p4, p5, p6:
            offline.download("test-model")
            # N4: installed() بيشترط إن اسم الموديل يبقى من MODELS — فـMODELS
            # لازم يفضل مترقّع لـ"test-model" وقت الفحص (بعد فك الـpatches
            # "test-model" مش من الموديلات الحقيقية فكان هيرجّع None).
            self.assertEqual(offline.installed(), "test-model")
            bin_dir = os.path.join(core.BASE, "offline", "bin")
            model_dir = os.path.join(core.BASE, "offline", "models")
            self.assertEqual(sorted(os.listdir(bin_dir)), ["ggml.dll", "whisper-cli.exe"])
            self.assertEqual(os.listdir(model_dir), ["test-model.bin"])

    def test_switching_model_removes_superseded_files(self):
        # تبديل الموديل: القديم (150–190 MB) والملفات اللي التثبيت الجديد مبقاش فيها
        # بتتمسح — غير كده كانت بتفضل يتامى ومحدش يقدر يشيلها من الواجهة
        two = {"m-a": (MODEL_URL, _sha256(MODEL_BYTES), len(MODEL_BYTES)),
               "m-b": (MODEL_URL, _sha256(MODEL_BYTES), len(MODEL_BYTES))}
        p1, p2, p3, p4, p5, p6 = _download_patches()
        with mock.patch.object(offline, "MODELS", two), p2, p3, p4, p5, p6:
            offline.download("m-a")
            root = os.path.join(core.BASE, "offline")
            # ملف من تثبيت قديم مسجّل في المانيڨست + ملف المستخدم مش مسجّل
            _write(os.path.join(root, "bin", "old.dll"), b"OLD")
            with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
                m = json.load(f)
            m["files"]["bin/old.dll"] = 3
            with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(m, f)
            _write(os.path.join(root, "models", "notes.txt"), b"mine")
            offline.download("m-b")
            self.assertEqual(offline.installed(), "m-b")
            self.assertEqual(sorted(os.listdir(os.path.join(root, "models"))), ["m-b.bin", "notes.txt"])
            self.assertFalse(os.path.exists(os.path.join(root, "bin", "old.dll")))
            with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
                self.assertNotIn("bin/old.dll", json.load(f)["files"])

    def test_progress_reaches_one(self):
        fractions = []
        p1, p2, p3, p4, p5, p6 = _download_patches()
        with p1, p2, p3, p4, p5, p6:
            offline.download("test-model", progress=fractions.append)
        self.assertIn(1.0, fractions)
        self.assertTrue(all(0.0 <= f <= 1.0 for f in fractions))

    def test_unknown_model_raises(self):
        with self.assertRaises(ValueError):
            offline.download("nope")

    def test_help_failure_raises_and_cleans_staging(self):
        p1, p2, p3, p4, p5, p6 = _download_patches()
        p6 = mock.patch.object(offline, "_run", return_value=SimpleNamespace(returncode=1))
        with p1, p2, p3, p4, p5, p6:
            with self.assertRaises(RuntimeError):
                offline.download("test-model")
        self.assertIsNone(offline.installed())
        staging = os.path.join(core.BASE, "offline", ".staging")
        self.assertFalse(os.path.exists(staging) and os.listdir(staging))


# ── remove() ──────────────────────────────────────────────────────────────────
class TestRemove(_BaseCase):
    def test_removes_installed_files(self):
        self._install("base")
        self.assertEqual(offline.installed(), "base")
        offline.remove()
        self.assertIsNone(offline.installed())
        self.assertFalse(os.path.exists(os.path.join(core.BASE, "offline", "manifest.json")))


class TestDamagedPackCleanup(_BaseCase):
    """تثبيت بايظ (مانيڨست بايظ/ملف ناقص): installed() = None بس الإزالة لازم تشيل الملفات."""

    def test_residual_false_on_clean_base(self):
        self.assertFalse(offline.residual())

    def test_remove_clears_files_when_manifest_is_unreadable(self):
        root = self._install("base")
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{مش json")
        _write(os.path.join(root, "bin", "ggml.dll"), b"DLL")
        self.assertIsNone(offline.installed())
        self.assertTrue(offline.residual())
        offline.remove()
        self.assertFalse(offline.residual())
        for rel in ("bin/whisper-cli.exe", "bin/ggml.dll", "models/base.bin", "manifest.json"):
            self.assertFalse(os.path.exists(os.path.join(root, rel)), rel)

    def _manifest(self, data):
        root = self._install("base")
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        return root

    def test_malformed_manifest_shapes_are_not_installed(self):
        # JSON سليم بس شكله غلط لازم يرجّع None مش يرمي — bootstrap بيناديه
        for bad in ([], "x", {"model": ["base"], "files": {}},
                    {"model": "base", "files": {"bin/whisper-cli.exe": "كبير",
                                                "models/base.bin": 5}},
                    {"model": "base", "files": {"bin/whisper-cli.exe": None,
                                                "models/base.bin": 5}}):
            self._tmp.cleanup(); os.makedirs(self._tmp.name)
            self._manifest(bad)
            self.assertIsNone(offline.installed(), bad)
            self.assertTrue(offline.residual())

    def test_manifest_without_executable_is_not_installed(self):
        # الموديل لوحده في المانيڨست مش تثبيت — من غير whisper-cli مفيش تفريغ
        self._manifest({"model": "base", "files": {"models/base.bin": 5}})
        self.assertIsNone(offline.installed())

    def test_remove_keeps_unknown_user_files(self):
        root = self._install("base")
        _write(os.path.join(root, "models", "notes.txt"), b"mine")
        offline.remove()
        self.assertTrue(os.path.exists(os.path.join(root, "models", "notes.txt")))


# ── احتواء المانيڨست (N4) ────────────────────────────────────────────────────
class TestManifestContainment(_BaseCase):
    def test_installed_none_when_model_not_known(self):
        # الموديل المسجّل مش من offline.MODELS — المانيڨست مش سليم فرجّع None
        root = os.path.join(self._tmp.name, "offline")
        bin_dir = os.path.join(root, "bin")
        os.makedirs(bin_dir)
        _write(os.path.join(bin_dir, "whisper-cli.exe"), b"EXE")
        manifest = {"model": "../x", "version": offline.WHISPER_CPP_VERSION,
                    "files": {"bin/whisper-cli.exe": 3}}
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        self.assertIsNone(offline.installed())

    def test_installed_none_when_path_escapes_root(self):
        # مسار في المانيڨست بيطلع برّه الجذر — installed() لازم يرجّع None
        root = self._install("base")
        manifest_path = os.path.join(root, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        data["files"]["../../outside.bin"] = 4
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self.assertIsNone(offline.installed())

    def test_remove_leaves_outside_file(self):
        # N4: ملف بيطلع برّه الجذر في المانيڨست — remove() ميمسحهوش
        root = self._install("base")
        outside = os.path.join(self._tmp.name, "outside.txt")
        _write(outside, b"KEEP")
        manifest_path = os.path.join(root, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        data["files"]["../outside.txt"] = 4
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        offline.remove()
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(os.path.getsize(outside), 4)
        self.assertFalse(os.path.exists(manifest_path))


# ── transcribe() ──────────────────────────────────────────────────────────────
class TestTranscribe(_BaseCase):
    def _run_writing(self, text, returncode=0, raise_=None):
        """fake لـoffline._run: بيكتب .txt عند out_base وبيرجّع returncode (أو بيرمي)."""
        seen = {}

        def _run(cmd, timeout=None):
            out_base = cmd[cmd.index("-of") + 1]
            seen["out_base"] = out_base
            if raise_ is not None:
                raise raise_
            with open(out_base + ".txt", "w", encoding="utf-8") as f:
                f.write(text)
            return SimpleNamespace(returncode=returncode)

        return _run, seen

    def test_returns_text_and_deletes_txt(self):
        self._install("base")
        fake_run, seen = self._run_writing("  النص المفرّغ  ")
        with mock.patch.object(offline, "_run", fake_run):
            text = offline.transcribe("w.wav", "ar")
        self.assertEqual(text, "النص المفرّغ")
        self.assertFalse(os.path.exists(seen["out_base"] + ".txt"))

    def test_read_result_tolerates_coarse_mtime(self):
        # NTFS بيسجّل mtime بساعة أخشن من time.time() — ملف اتكتب بعد start
        # ممكن mtime بتاعه يطلع قبله بأجزاء من الثانية ولازم يتقبل
        path = os.path.join(self._tmp.name, "r.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(" نص ")
        start = time.time()
        os.utime(path, (start - 0.02, start - 0.02))
        self.assertEqual(offline._read_result(path, start), "نص")

    def test_read_result_rejects_old_file(self):
        path = os.path.join(self._tmp.name, "r.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("قديم")
        start = time.time()
        os.utime(path, (start - 60, start - 60))
        self.assertIsNone(offline._read_result(path, start))

    def test_stale_output_removed_before_run(self):
        # ملف .txt سابق بنفس الاسم مايترجعش لو whisper ماكتبش حاجة
        self._install("base")
        seen = {}

        def _run(cmd, timeout=None):
            seen["existed"] = os.path.exists(cmd[cmd.index("-of") + 1] + ".txt")
            return SimpleNamespace(returncode=0)

        stale = os.path.join(self._tmp.name, "emlaa_offline_1234567.txt")
        with open(stale, "w", encoding="utf-8") as f:
            f.write("نص قديم")
        os.utime(stale, (1234.6, 1234.6))   # mtime "بعد" start — الحارس لوحده ميكفيش
        with mock.patch.object(offline.tempfile, "gettempdir", return_value=self._tmp.name),                 mock.patch.object(offline.time, "time", return_value=1234.567),                 mock.patch.object(offline, "_run", _run):
            with self.assertRaises(RuntimeError):
                offline.transcribe("w.wav", "ar")
        self.assertFalse(seen["existed"])
        self.assertFalse(os.path.exists(stale))

    def test_requires_model_installed(self):
        with self.assertRaises(RuntimeError):
            offline.transcribe("w.wav", "ar")

    def test_model_selection_is_inside_lock(self):
        # N5: installed() لازم يتنده جوه اللوك — عشان remove() (نفس اللوك)
        # ميقدرش يمسح الملفات بين اختيار الموديل وتنفيذه. لو اتناده برّه،
        # acquire غير الحاجب هينجح وبنفشل الاختبار.
        self._install("base")
        seen = {}
        real_installed = offline.installed

        def installed_checking_lock():
            held = offline._lock.acquire(blocking=False)
            seen["locked"] = not held
            if held:
                offline._lock.release()
            return real_installed()

        fake_run, _ = self._run_writing("نص")
        with mock.patch.object(offline, "installed", installed_checking_lock), \
                mock.patch.object(offline, "_run", fake_run):
            offline.transcribe("w.wav", "ar")
        self.assertTrue(seen["locked"])

    def test_empty_result_raises(self):
        self._install("base")
        fake_run, seen = self._run_writing("   \n ")
        with mock.patch.object(offline, "_run", fake_run):
            with self.assertRaises(RuntimeError):
                offline.transcribe("w.wav", "ar")
        self.assertFalse(os.path.exists(seen["out_base"] + ".txt"))

    def test_nonzero_exit_raises(self):
        self._install("base")
        fake_run, seen = self._run_writing("النص", returncode=1)
        with mock.patch.object(offline, "_run", fake_run):
            with self.assertRaises(RuntimeError):
                offline.transcribe("w.wav", "ar")

    def test_timeout_raises(self):
        self._install("base")
        fake_run, seen = self._run_writing("", raise_=subprocess.TimeoutExpired(["x"], 120))
        with mock.patch.object(offline, "_run", fake_run):
            with self.assertRaises(RuntimeError):
                offline.transcribe("w.wav", "ar")


# ── فحص بصمة الحزمة (Task 20) ─────────────────────────────────────────────────
class TestVerify(_BaseCase):
    def test_verify_match_is_cached(self):
        # فحص سليم بيتخزّن — الفحص التاني من نفس المانيڨست ميهاشيش تاني
        self._install("base")
        with mock.patch.object(offline, "_sha256_file", wraps=offline._sha256_file) as h:
            self.assertTrue(offline.verify())
            first = h.call_count
            self.assertTrue(offline.verify())
            self.assertEqual(h.call_count, first)

    def test_transcribe_hashes_once_per_session(self):
        # التفريغ نفسه لازم يستخدم الكاش — غير كده كل تفريغ بيعيد هاش 150–190 MB
        self._install("base")

        def fake_run(cmd, timeout=None):
            with open(cmd[cmd.index("-of") + 1] + ".txt", "w", encoding="utf-8") as f:
                f.write("نص")
            return SimpleNamespace(returncode=0)

        with mock.patch.object(offline, "_run", fake_run),                 mock.patch.object(offline, "_sha256_file", wraps=offline._sha256_file) as h:
            offline.transcribe("w.wav", "ar")
            first = h.call_count
            offline.transcribe("w.wav", "ar")
            offline.transcribe("w.wav", "ar")
        self.assertGreater(first, 0)
        self.assertEqual(h.call_count, first)

    def test_cached_verification_reflects_verify(self):
        self.assertIsNone(offline.cached_verification())
        self._install("base")
        self.assertIsNone(offline.cached_verification())   # لسه متفحصش
        self.assertTrue(offline.verify())
        self.assertIs(offline.cached_verification(), True)

    def test_same_size_flipped_byte_detected_and_transcribe_refuses(self):
        # بايت اتقلب من غير ما الحجم يتغيّر — installed() بيعدّي بس verify() بيمسكه
        self._install("base")
        p = os.path.join(self._tmp.name, "offline", "models", "base.bin")
        data = bytearray(open(p, "rb").read())
        data[0] ^= 0xFF
        _write(p, bytes(data))
        with mock.patch.object(offline, "_run") as run:
            with self.assertRaises(RuntimeError) as cm:
                offline.transcribe("w.wav", "ar")
        run.assert_not_called()
        self.assertEqual(str(cm.exception), "الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات")

    def test_cache_cleared_by_remove(self):
        self._install("base")
        self.assertTrue(offline.verify())
        self.assertTrue(offline._verify_cache)
        offline.remove()
        self.assertFalse(offline._verify_cache)

    def test_cache_cleared_by_download(self):
        self._install("base")
        self.assertTrue(offline.verify())
        self.assertTrue(offline._verify_cache)
        p1, p2, p3, p4, p5, p6 = _download_patches()
        with p1, p2, p3, p4, p5, p6:
            offline.download("test-model")
        self.assertFalse(offline._verify_cache)

    def test_legacy_manifest_wrong_model_hash_detected(self):
        # مانيڨست قديم من غير "sha256": الموديل بيتقارن بـMODELS pin فبيقفش
        root = os.path.join(self._tmp.name, "offline")
        bin_dir = os.path.join(root, "bin")
        model_dir = os.path.join(root, "models")
        os.makedirs(bin_dir); os.makedirs(model_dir)
        _write(os.path.join(bin_dir, "whisper-cli.exe"), b"EXE")
        _write(os.path.join(model_dir, "base.bin"), b"WRONG-MODEL-CONTENT")
        manifest = {"model": "base", "version": offline.WHISPER_CPP_VERSION,
                    "files": {"bin/whisper-cli.exe": 3, "models/base.bin": 19}}
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        self.assertFalse(offline.verify())

    def test_download_writes_sha256_map(self):
        p1, p2, p3, p4, p5, p6 = _download_patches()
        with p1, p2, p3, p4, p5, p6:
            offline.download("test-model")
        manifest_path = os.path.join(core.BASE, "offline", "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("sha256", data)
        self.assertEqual(sorted(data["sha256"].keys()), sorted(data["files"].keys()))
        # الموديل = البصمة المثبّتة، الـexe/الـdll = بصمة الملف الفعلي
        self.assertEqual(data["sha256"]["models/test-model.bin"], _sha256(MODEL_BYTES))
        self.assertEqual(data["sha256"]["bin/whisper-cli.exe"], _sha256(b"EXE"))
        self.assertEqual(data["sha256"]["bin/ggml.dll"], _sha256(b"GGML"))


# ── NetworkError ──────────────────────────────────────────────────────────────
class TestNetworkError(unittest.TestCase):
    def test_is_runtime_error(self):
        self.assertTrue(issubclass(providers.NetworkError, RuntimeError))

    def test_has_marker(self):
        self.assertTrue(getattr(providers.NetworkError("x"), "is_network", False))


class TestProviderNetworkMapping(unittest.TestCase):
    def test_deepgram_urlerror_raises_network_error(self):
        cl = providers.Client("deepgram", "test-key")
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch("urllib.request.urlopen",
                            side_effect=urllib.error.URLError("dns fail")):
                with self.assertRaises(providers.NetworkError):
                    cl._deepgram_request(wav, "ar")

    def test_deepgram_http_error_stays_runtime_error_with_status(self):
        cl = providers.Client("deepgram", "test-key")
        err = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(RuntimeError) as cm:
                    cl._deepgram_request(wav, "ar")
        self.assertNotIsInstance(cm.exception, providers.NetworkError)
        self.assertEqual(cm.exception.status, 401)

    def test_gemini_network_error(self):
        cl = providers.Client("gemini", "test-key")
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch.object(providers, "_post_json",
                                   side_effect=urllib.error.URLError("dns fail")):
                with self.assertRaises(providers.NetworkError):
                    cl._gemini_transcribe(wav, "ar")

    def test_deepgram_incomplete_read_raises_network_error(self):
        # القراية قاطعة في النص (IncompleteRead) = قطع اتصال → NetworkError
        cl = providers.Client("deepgram", "test-key")
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch("urllib.request.urlopen",
                            side_effect=http.client.IncompleteRead(b"x", 10)):
                with self.assertRaises(providers.NetworkError):
                    cl._deepgram_request(wav, "ar")

    def test_oa_transcribe_maps_connection_error(self):
        import openai
        import httpx
        cl = providers.Client("groq", "test-key")
        fake = mock.Mock()
        fake.timeout = None
        req = httpx.Request("POST", "https://api.example.com")
        fake.audio.transcriptions.create.side_effect = \
            openai.APIConnectionError(message="boom", request=req)
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch.object(cl, "_openai", return_value=fake):
                with self.assertRaises(providers.NetworkError):
                    cl._oa_transcribe(wav, "ar")

    def test_oa_transcribe_maps_timeout_error(self):
        import openai
        import httpx
        cl = providers.Client("groq", "test-key")
        fake = mock.Mock()
        fake.timeout = None
        req = httpx.Request("POST", "https://api.example.com")
        fake.audio.transcriptions.create.side_effect = openai.APITimeoutError(req)
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(tmp)
            with mock.patch.object(cl, "_openai", return_value=fake):
                with self.assertRaises(providers.NetworkError):
                    cl._oa_transcribe(wav, "ar")


class TestSttTimeout(unittest.TestCase):
    """مهلة الاتصال ١٠ ثواني للتفريغ عبر httpx — من غير ما تقصّر مهلة القراية."""

    def test_connect_is_10_and_read_preserved(self):
        import httpx
        cl = providers.Client("groq", "test-key")
        t = cl._stt_timeout()
        self.assertIsInstance(t, httpx.Timeout)
        self.assertEqual(t.connect, 10.0)
        self.assertGreater(t.read, 0)


# ── is_network_error() ────────────────────────────────────────────────────────
class TestIsNetworkError(unittest.TestCase):
    def test_none_is_false(self):
        self.assertFalse(smart.is_network_error(None))

    def test_network_error_is_true(self):
        self.assertTrue(smart.is_network_error(providers.NetworkError("x")))

    def test_connection_error_true(self):
        self.assertTrue(smart.is_network_error(ConnectionError("refused")))

    def test_timeout_error_true(self):
        self.assertTrue(smart.is_network_error(TimeoutError("t")))

    def test_socket_timeout_true(self):
        self.assertTrue(smart.is_network_error(socket.timeout("t")))

    def test_urlerror_true(self):
        self.assertTrue(smart.is_network_error(urllib.error.URLError("dns")))

    def test_http_error_false(self):
        e = urllib.error.HTTPError("https://x", 401, "x", {}, io.BytesIO(b"{}"))
        self.assertFalse(smart.is_network_error(e))

    def test_incomplete_read_true(self):
        self.assertTrue(smart.is_network_error(http.client.IncompleteRead(b"x", 10)))

    def test_remote_disconnected_true(self):
        self.assertTrue(smart.is_network_error(http.client.RemoteDisconnected("x")))

    def test_runtime_error_false(self):
        self.assertFalse(smart.is_network_error(RuntimeError("x")))

    def test_value_error_false(self):
        self.assertFalse(smart.is_network_error(ValueError("x")))


# ── P1: التنزيل ميمنعش التفريغ والمسح ─────────────────────────────────────────
class _BlockingOpener:
    """opener بيعمل block على الموديل URL لحد ما نسيب release — لمحاكاة تنزيل معلّق."""

    def __init__(self, block_url):
        self.block_url = block_url
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, url):
        if url == self.block_url:
            # علامة جوّه الـstaging عشان نتحقق إن remove() ممسحهاش وهو التنزيل شغّال
            import core
            staging = os.path.join(core.BASE, "offline", ".staging")
            os.makedirs(staging, exist_ok=True)
            with open(os.path.join(staging, "marker.tmp"), "wb") as f:
                f.write(b"x")
            self.started.set()
            self.release.wait()
            raise urllib.error.URLError("اتلغى التنزيل")
        return io.BytesIO(b"")


class TestDownloadLocking(_BaseCase):
    def _patches(self, opener):
        # "base" لازم يفضل في MODELS عشان installed() (الموديل المثبّت بتاع transcribe)
        # يرجّع اسمه — غير كده التثبيت اللي بنعمله بـ_install("base") بيتشاف مش معروف.
        models = {
            "test-model": (MODEL_URL, _sha256(MODEL_BYTES), len(MODEL_BYTES)),
            "base": (MODEL_URL, _sha256(MODEL_BYTES), len(MODEL_BYTES)),
        }
        return (
            mock.patch.object(offline, "MODELS", models),
            mock.patch.object(offline, "WHISPER_CPP_URL", ZIP_URL),
            mock.patch.object(offline, "WHISPER_CPP_SHA256", _sha256(ZIP_BYTES)),
            mock.patch.object(offline, "WHISPER_CPP_SIZE", len(ZIP_BYTES)),
            mock.patch.object(offline, "_opener", opener),
        )

    def _fake_run(self, cmd, timeout=None):
        out_base = cmd[cmd.index("-of") + 1]
        with open(out_base + ".txt", "w", encoding="utf-8") as f:
            f.write("النص")
        return SimpleNamespace(returncode=0)

    def _start_blocked_download(self, opener):
        """بيشغّل download في ثريد، ويستنى لحد ما الـopener يوصل للـblock، ويرجّع الثريد."""

        def _run_download():
            try:
                offline.download("test-model")
            except urllib.error.URLError:
                pass    # المتوقع: الـopener بيرمي بعد ما نسيبه

        t = threading.Thread(target=_run_download)
        t.daemon = True
        # لو assertion فشل التنزيل لازم يتساب برضه — غير كده الاختبار اللي بعده بيعلّق على اللوك
        self.addCleanup(t.join, 5)
        self.addCleanup(opener.release.set)
        t.start()
        self.assertTrue(opener.started.wait(5), "التنزيل ماعملش block في الـopener")
        return t

    def test_transcribe_and_remove_not_blocked_by_download(self):
        self._install("base")
        opener = _BlockingOpener(MODEL_URL)
        p1, p2, p3, p4, p5 = self._patches(opener)
        with p1, p2, p3, p4, p5, mock.patch.object(offline, "_run", self._fake_run):
            t = self._start_blocked_download(opener)

            result = {}

            def worker():
                try:
                    result["text"] = offline.transcribe("w.wav", "ar")
                    offline.remove()
                except Exception as e:      # pragma: no cover
                    result["err"] = e

            w = threading.Thread(target=worker)
            w.start()
            w.join(5)
            self.assertFalse(w.is_alive(), "transcribe/remove استنّوا التنزيل")
            self.assertNotIn("err", result)
            self.assertEqual(result["text"], "النص")
            opener.release.set()
            t.join(5)

    def test_remove_does_not_clear_staging_of_active_download(self):
        self._install("base")
        opener = _BlockingOpener(MODEL_URL)
        p1, p2, p3, p4, p5 = self._patches(opener)
        with p1, p2, p3, p4, p5:
            t = self._start_blocked_download(opener)
            r = threading.Thread(target=offline.remove, daemon=True)
            r.start()
            r.join(5)
            self.assertFalse(r.is_alive(), "remove استنّى التنزيل")
            staging = os.path.join(core.BASE, "offline", ".staging")
            self.assertTrue(os.path.isdir(staging), "remove مسح staging بتاع تنزيل شغّال")
            self.assertTrue(os.path.exists(os.path.join(staging, "marker.tmp")))
            opener.release.set()
            t.join(5)


class TestOpenTimeout(unittest.TestCase):
    def test_open_passes_download_timeout(self):
        with mock.patch.object(offline, "_opener", None), \
                mock.patch("urllib.request.urlopen") as uo:
            offline._open("https://x/y")
        uo.assert_called_once_with("https://x/y", timeout=offline.DOWNLOAD_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
