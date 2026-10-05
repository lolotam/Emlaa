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
import unittest
import urllib.error
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

    def tearDown(self):
        self._base.stop()
        self._tmp.cleanup()

    def _install(self, model="base"):
        """بيجهّز تثبيت سليم (manifest + bin + model) جوه الـBASE المؤقت."""
        root = os.path.join(self._tmp.name, "offline")
        bin_dir = os.path.join(root, "bin")
        model_dir = os.path.join(root, "models")
        os.makedirs(bin_dir); os.makedirs(model_dir)
        _write(os.path.join(bin_dir, "whisper-cli.exe"), b"EXE")
        _write(os.path.join(model_dir, model + ".bin"), b"MODEL")
        manifest = {"model": model, "version": offline.WHISPER_CPP_VERSION,
                    "files": {"bin/whisper-cli.exe": 3, "models/" + model + ".bin": 5}}
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
        self.assertEqual(offline.installed(), "test-model")
        bin_dir = os.path.join(core.BASE, "offline", "bin")
        model_dir = os.path.join(core.BASE, "offline", "models")
        self.assertEqual(sorted(os.listdir(bin_dir)), ["ggml.dll", "whisper-cli.exe"])
        self.assertEqual(os.listdir(model_dir), ["test-model.bin"])

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

    def test_requires_model_installed(self):
        with self.assertRaises(RuntimeError):
            offline.transcribe("w.wav", "ar")

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

    def test_runtime_error_false(self):
        self.assertFalse(smart.is_network_error(RuntimeError("x")))

    def test_value_error_false(self):
        self.assertFalse(smart.is_network_error(ValueError("x")))


if __name__ == "__main__":
    unittest.main()
