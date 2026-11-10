# -*- coding: utf-8 -*-
"""
اختبارات محرّك Nemotron المحلي (source/nemotron.py) — من غير شبكة ولا ملفات حقيقية.

الاختبارات بتتحكّم في كل حاجة: الـopener (مكان الشبكة)، و_run (مكان العملية)،
والبصمات والأحجام المثبّتة (عشان البايتات الوهمية تتطابق). وcore.BASE متغيّر
لمجلد مؤقت — فمفيش أي ملف بيتلمس برّه المجلد ده.
"""
import io
import os
import sys
import json
import hashlib
import zipfile
import subprocess
import tempfile
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core        # noqa: E402
import asr_pack    # noqa: E402
import nemotron    # noqa: E402


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _make_zip(entries):
    """zip في الذاكرة من {اسم: بايتات} — للفك من غير شبكة."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.filename = name
            z.writestr(info, data)
    return buf.getvalue()


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


MODEL_BYTES = b"FAKE-MODEL"
RUNTIME_BYTES = _make_zip({
    "bin/nemo-speech.exe": b"EXE",
    "bin/ggml.dll": b"GGML",
    "share/licenses/nemo-speech/LICENSE": b"LIC",
})


def _pins():
    """البصمات والأحجام المثبّتة بل بايتات الاختبار — عشان التحقق يعدّي."""
    return (
        mock.patch.object(nemotron, "MODEL_URL", "https://x/model.gguf"),
        mock.patch.object(nemotron, "MODEL_SHA256", _sha256(MODEL_BYTES)),
        mock.patch.object(nemotron, "MODEL_SIZE", len(MODEL_BYTES)),
        mock.patch.object(nemotron, "NEMO_SPEECH_URL", "https://x/runtime.zip"),
        mock.patch.object(nemotron, "NEMO_SPEECH_SHA256", _sha256(RUNTIME_BYTES)),
        mock.patch.object(nemotron, "NEMO_SPEECH_SIZE", len(RUNTIME_BYTES)),
    )


def _opener():
    return mock.patch.object(nemotron, "_opener",
                             _FakeOpener({"https://x/model.gguf": MODEL_BYTES,
                                          "https://x/runtime.zip": RUNTIME_BYTES}))


class _BaseCase(unittest.TestCase):
    """بيقفل core.BASE على مجلد مؤقت — عشان nemotron ميمسش BASE الحقيقي أبدًا."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._base = mock.patch.object(core, "BASE", self._tmp.name)
        self._base.start()
        nemotron._verify_cache.clear()
        self.addCleanup(nemotron._verify_cache.clear)

    def tearDown(self):
        self._base.stop()
        self._tmp.cleanup()

    def _install(self):
        """ينزّل الحزمة كاملة (شبكة وعملية مزيّفتين) — زي ما المستخدم بيعمل."""
        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener(), \
                mock.patch.object(nemotron, "_run",
                                  return_value=SimpleNamespace(returncode=0)):
            nemotron.download()
        return os.path.join(self._tmp.name, "offline", "nemo")


# ── الأرقام المثبّتة ──────────────────────────────────────────────────────────
class TestPins(unittest.TestCase):
    """الأرقام لازم تفضل كما هي — تغييرها من غير مراجعة = تنزيل ملف تاني."""

    def test_runtime_pin(self):
        self.assertEqual(nemotron.NEMO_SPEECH_VERSION, "0.3.0")
        self.assertEqual(nemotron.NEMO_SPEECH_SHA256,
                         "4ed9740e361e4653f56c3dce7d1e81883a1c8b831c1bd7d01567fff1130b5b05")
        self.assertEqual(nemotron.NEMO_SPEECH_SIZE, 8694509)
        self.assertIn("v0.3.0", nemotron.NEMO_SPEECH_URL)
        self.assertIn("windows-x86_64-cpu", nemotron.NEMO_SPEECH_URL)

    def test_model_pin(self):
        self.assertEqual(nemotron.MODEL_SHA256,
                         "3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1")
        self.assertEqual(nemotron.MODEL_SIZE, 742090464)
        self.assertIn(nemotron.MODEL_REVISION, nemotron.MODEL_URL)
        self.assertTrue(nemotron.MODEL_URL.endswith(
            "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"))

    def test_pack_size_is_model_plus_runtime(self):
        self.assertEqual(nemotron.PACKS[nemotron.MODEL_ID],
                         nemotron.MODEL_SIZE + nemotron.NEMO_SPEECH_SIZE)


# ── اللغة ─────────────────────────────────────────────────────────────────────
class TestLanguageCode(unittest.TestCase):
    def test_arabic_and_english(self):
        self.assertEqual(nemotron.language_code("ar"), "ar-AR")
        self.assertEqual(nemotron.language_code("en"), "en-US")

    def test_none_is_auto(self):
        self.assertEqual(nemotron.language_code(None), "auto")

    def test_unknown_is_auto(self):
        self.assertEqual(nemotron.language_code("fr"), "auto")
        self.assertEqual(nemotron.language_code(""), "auto")


# ── التثبيت ───────────────────────────────────────────────────────────────────
class TestInstall(_BaseCase):
    def test_none_without_manifest(self):
        self.assertIsNone(nemotron.installed())

    def test_install_writes_runtime_and_model(self):
        root = self._install()
        self.assertEqual(nemotron.installed(), "nemotron-3.5")
        self.assertTrue(os.path.exists(os.path.join(root, "runtime", "bin", "nemo-speech.exe")))
        self.assertTrue(os.path.exists(os.path.join(root, "runtime", "bin", "ggml.dll")))
        self.assertTrue(os.path.exists(os.path.join(root, "models", nemotron.MODEL_FILE)))

    def test_manifest_records_the_exe_and_hashes(self):
        root = self._install()
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["model"], "nemotron-3.5")
        self.assertEqual(data["exe"], "runtime/bin/nemo-speech.exe")
        self.assertIn("models/" + nemotron.MODEL_FILE, data["files"])
        self.assertEqual(sorted(data["sha256"].keys()), sorted(data["files"].keys()))

    def test_staging_is_clean_after_install(self):
        root = self._install()
        self.assertFalse(os.path.exists(os.path.join(root, ".staging")))

    def test_none_when_model_file_missing(self):
        root = self._install()
        os.remove(os.path.join(root, "models", nemotron.MODEL_FILE))
        self.assertIsNone(nemotron.installed())

    def test_none_when_runtime_missing(self):
        root = self._install()
        os.remove(os.path.join(root, "runtime", "bin", "nemo-speech.exe"))
        self.assertIsNone(nemotron.installed())

    def test_none_when_manifest_corrupt(self):
        root = self._install()
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{مش json")
        self.assertIsNone(nemotron.installed())

    def test_hash_mismatch_leaves_nothing_installed(self):
        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener(), \
                mock.patch.object(nemotron, "MODEL_SHA256", _sha256(b"WRONG")), \
                mock.patch.object(nemotron, "_run",
                                  return_value=SimpleNamespace(returncode=0)):
            with self.assertRaises(RuntimeError):
                nemotron.download()
        self.assertIsNone(nemotron.installed())

    def test_smoke_test_failure_cancels_the_install(self):
        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener(), \
                mock.patch.object(nemotron, "_run",
                                  return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(RuntimeError):
                nemotron.download()
        self.assertIsNone(nemotron.installed())

    def test_progress_reaches_one(self):
        fractions = []
        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener(), \
                mock.patch.object(nemotron, "_run",
                                  return_value=SimpleNamespace(returncode=0)):
            nemotron.download(progress=fractions.append)
        self.assertIn(1.0, fractions)
        self.assertTrue(all(0.0 <= f <= 1.0 for f in fractions))


# ── أمان مسار الأرشيف ─────────────────────────────────────────────────────────
class TestExtractSafety(_BaseCase):
    def _extract(self, entries):
        path = os.path.join(self._tmp.name, "a.zip")
        with open(path, "wb") as f:
            f.write(_make_zip(entries))
        dest = os.path.join(self._tmp.name, "out")
        os.makedirs(dest, exist_ok=True)
        nemotron._extract_runtime(path, dest)
        return dest

    def test_keeps_the_runtime_tree(self):
        dest = self._extract({"bin/nemo-speech.exe": b"EXE", "bin/ggml.dll": b"GGML"})
        self.assertTrue(os.path.exists(os.path.join(dest, "bin", "nemo-speech.exe")))
        self.assertTrue(os.path.exists(os.path.join(dest, "bin", "ggml.dll")))

    def test_rejects_dotdot(self):
        with self.assertRaises(RuntimeError):
            self._extract({"../evil.exe": b"x"})

    def test_rejects_absolute_path(self):
        with self.assertRaises(RuntimeError):
            self._extract({os.path.abspath("evil.exe"): b"x"})

    def test_rejects_drive_path(self):
        with self.assertRaises(RuntimeError):
            self._extract({"C:/evil.exe": b"x"})

    def test_rejects_backslash(self):
        with self.assertRaises(RuntimeError):
            self._extract({"bin\\evil.exe": b"x"})


# ── الإلغاء ───────────────────────────────────────────────────────────────────
class TestCancel(_BaseCase):
    def test_cancel_during_smoke_test_prevents_publish(self):
        cancel = nemotron.threading.Event()

        def smoke(cmd, **kwargs):
            cancel.set()
            return SimpleNamespace(returncode=0)

        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener(), \
                mock.patch.object(nemotron, "_run", smoke):
            with self.assertRaises(asr_pack.Cancelled):
                nemotron.download(cancel=cancel)
        self.assertIsNone(nemotron.installed())
        self.assertFalse(os.path.exists(nemotron._dirs()[2]))

    def test_cancelled_download_leaves_nothing_installed(self):
        cancel = nemotron.threading.Event()
        cancel.set()
        p1, p2, p3, p4, p5, p6 = _pins()
        with p1, p2, p3, p4, p5, p6, _opener():
            with self.assertRaises(asr_pack.Cancelled):
                nemotron.download(cancel=cancel)
        self.assertIsNone(nemotron.installed())
        staging = os.path.join(self._tmp.name, "offline", "nemo", ".staging")
        self.assertFalse(os.path.exists(staging) and os.listdir(staging))


# ── الفحص ─────────────────────────────────────────────────────────────────────
class TestVerify(_BaseCase):
    def test_verify_true_after_install(self):
        self._install()
        self.assertTrue(nemotron.verify())

    def test_flipped_byte_is_detected(self):
        root = self._install()
        path = os.path.join(root, "models", nemotron.MODEL_FILE)
        data = bytearray(open(path, "rb").read())
        data[0] ^= 0xFF
        with open(path, "wb") as f:
            f.write(bytes(data))
        self.assertFalse(nemotron.verify())

    def test_cached_verification_reflects_verify(self):
        self.assertIsNone(nemotron.cached_verification())
        self._install()
        self.assertIsNone(nemotron.cached_verification())
        self.assertTrue(nemotron.verify())
        self.assertIs(nemotron.cached_verification(), True)

    def test_cache_cleared_by_remove(self):
        self._install()
        self.assertTrue(nemotron.verify())
        nemotron.remove()
        self.assertFalse(nemotron._verify_cache)


# ── الإزالة ───────────────────────────────────────────────────────────────────
class TestRemove(_BaseCase):
    def test_remove_clears_everything(self):
        root = self._install()
        self.assertTrue(nemotron.residual())
        nemotron.remove()
        self.assertIsNone(nemotron.installed())
        self.assertFalse(nemotron.residual())
        self.assertFalse(os.path.exists(os.path.join(root, "models", nemotron.MODEL_FILE)))

    def test_remove_keeps_unknown_user_files(self):
        root = self._install()
        note = os.path.join(root, "models", "notes.txt")
        with open(note, "wb") as f:
            f.write(b"mine")
        nemotron.remove()
        self.assertTrue(os.path.exists(note))


# ── التفريغ ───────────────────────────────────────────────────────────────────
class TestTranscribe(_BaseCase):
    def _run_writing(self, text, returncode=0, raise_=None):
        """fake لـnemotron._run: بيكتب ملف الناتج عند --output وبيرجّع returncode."""
        seen = {}

        def _run(cmd, timeout=None):
            out_path = cmd[cmd.index("--output") + 1]
            seen["cmd"] = cmd
            seen["timeout"] = timeout
            if raise_ is not None:
                raise raise_
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
            return SimpleNamespace(returncode=returncode, stderr=b"")

        return _run, seen

    def test_returns_the_transcript(self):
        self._install()
        fake_run, seen = self._run_writing("  النص المفرّغ  \n")
        with mock.patch.object(nemotron, "_run", fake_run):
            text = nemotron.transcribe("w.wav", "ar")
        self.assertEqual(text, "النص المفرّغ")
        self.assertFalse(os.path.exists(seen["cmd"][seen["cmd"].index("--output") + 1]))

    def test_command_carries_model_and_language(self):
        self._install()
        fake_run, seen = self._run_writing("نص")
        with mock.patch.object(nemotron, "_run", fake_run):
            nemotron.transcribe("w.wav", "en")
        cmd = seen["cmd"]
        self.assertEqual(cmd[1], "transcribe")
        self.assertEqual(cmd[cmd.index("--model") + 1],
                         os.path.join(self._tmp.name, "offline", "nemo", "models", nemotron.MODEL_FILE))
        self.assertEqual(cmd[cmd.index("--language") + 1], "en-US")
        self.assertIn("--force", cmd)

    def test_language_tag_is_stripped(self):
        self._install()
        fake_run, _seen = self._run_writing("النص المفرّغ.<ar-AR>\n")
        with mock.patch.object(nemotron, "_run", fake_run):
            text = nemotron.transcribe("w.wav", None)
        self.assertEqual(text, "النص المفرّغ.")

    def test_requires_install(self):
        with self.assertRaises(RuntimeError):
            nemotron.transcribe("w.wav", "ar")

    def test_empty_result_raises(self):
        self._install()
        fake_run, _seen = self._run_writing("   \n")
        with mock.patch.object(nemotron, "_run", fake_run):
            with self.assertRaises(RuntimeError):
                nemotron.transcribe("w.wav", "ar")

    def test_nonzero_exit_raises_with_detail(self):
        self._install()

        def _run(cmd, timeout=None):
            return SimpleNamespace(returncode=2, stderr=b"boom happened")

        with mock.patch.object(nemotron, "_run", _run):
            with self.assertRaises(RuntimeError) as cm:
                nemotron.transcribe("w.wav", "ar")
        self.assertIn("boom happened", str(cm.exception))

    def test_timeout_raises(self):
        self._install()
        timeout_error = subprocess.TimeoutExpired("nemo-speech", nemotron.TRANSCRIBE_TIMEOUT)
        fake_run, seen = self._run_writing("", raise_=timeout_error)
        with mock.patch.object(nemotron, "_run", fake_run):
            with self.assertRaises(RuntimeError) as cm:
                nemotron.transcribe("w.wav", "ar")
        self.assertEqual(nemotron.TRANSCRIBE_TIMEOUT, 300)
        self.assertEqual(seen["timeout"], nemotron.TRANSCRIBE_TIMEOUT)
        self.assertIs(cm.exception.__cause__, timeout_error)
        self.assertIn("TimeoutExpired", str(cm.exception))

    def test_launch_failure_keeps_its_reason(self):
        self._install()
        launch_error = FileNotFoundError("missing nemo-speech.exe")
        fake_run, _seen = self._run_writing("", raise_=launch_error)
        with mock.patch.object(nemotron, "_run", fake_run):
            with self.assertRaises(RuntimeError) as cm:
                nemotron.transcribe("w.wav", "ar")
        self.assertIs(cm.exception.__cause__, launch_error)
        self.assertIn("FileNotFoundError", str(cm.exception))

    def test_corrupt_model_refuses_to_run(self):
        self._install()
        path = os.path.join(self._tmp.name, "offline", "nemo", "models", nemotron.MODEL_FILE)
        data = bytearray(open(path, "rb").read())
        data[0] ^= 0xFF
        with open(path, "wb") as f:
            f.write(bytes(data))
        with mock.patch.object(nemotron, "_run") as run:
            with self.assertRaises(RuntimeError) as cm:
                nemotron.transcribe("w.wav", "ar")
        run.assert_not_called()
        self.assertEqual(str(cm.exception),
                         "الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات")


if __name__ == "__main__":
    unittest.main()
