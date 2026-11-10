# -*- coding: utf-8 -*-
"""
تشابك المحرّكات المحلية: واجهة offline على Whisper و Nemotron، وسجلّ المحرّك،
وحالة الموديلات في الواجهة. مفيش شبكة ولا مفاتيح ولا BASE الحقيقي.
"""
import os
import sys
import json
import hashlib
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import offline    # noqa: E402
import nemotron   # noqa: E402
import chains     # noqa: E402
import app_web    # noqa: E402


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


class _BaseCase(unittest.TestCase):
    """بيقفل core.BASE على مجلد مؤقت — مفيش ملف بيتلمس برّه المجلد ده."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._base = mock.patch.object(core, "BASE", self._tmp.name)
        self._base.start()
        offline._verify_cache.clear()
        nemotron._verify_cache.clear()
        self.addCleanup(offline._verify_cache.clear)
        self.addCleanup(nemotron._verify_cache.clear)

    def tearDown(self):
        self._base.stop()
        self._tmp.cleanup()

    def _install_whisper(self, model="base"):
        """تثبيت whisper كامل (مانيڨست + bin + موديل) — زي الشكل الحقيقي."""
        root = os.path.join(self._tmp.name, "offline")
        bin_dir = os.path.join(root, "bin")
        model_dir = os.path.join(root, "models")
        os.makedirs(bin_dir)
        os.makedirs(model_dir)
        exe, model_data = b"EXE", b"MODEL"
        with open(os.path.join(bin_dir, "whisper-cli.exe"), "wb") as f:
            f.write(exe)
        with open(os.path.join(model_dir, model + ".bin"), "wb") as f:
            f.write(model_data)
        manifest = {"model": model, "version": offline.WHISPER_CPP_VERSION,
                    "files": {"bin/whisper-cli.exe": len(exe),
                              "models/" + model + ".bin": len(model_data)},
                    "sha256": {"bin/whisper-cli.exe": _sha256(exe),
                               "models/" + model + ".bin": _sha256(model_data)}}
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        return root

    def _install_nemotron(self):
        """تثبيت Nemotron كامل — مانيڨست + الـexe + الموديل."""
        root = os.path.join(self._tmp.name, "offline", "nemo")
        runtime = os.path.join(root, "runtime", "bin")
        models = os.path.join(root, "models")
        os.makedirs(runtime)
        os.makedirs(models)
        with open(os.path.join(runtime, "nemo-speech.exe"), "wb") as f:
            f.write(b"EXE")
        with open(os.path.join(models, nemotron.MODEL_FILE), "wb") as f:
            f.write(b"MODEL")
        files = {"runtime/bin/nemo-speech.exe": 3,
                 "models/" + nemotron.MODEL_FILE: 5}
        manifest = {"model": nemotron.MODEL_ID, "version": nemotron.NEMO_SPEECH_VERSION,
                    "exe": "runtime/bin/nemo-speech.exe", "files": files,
                    "sha256": {k: _sha256(v) for k, v in
                               (("runtime/bin/nemo-speech.exe", b"EXE"),
                                ("models/" + nemotron.MODEL_FILE, b"MODEL"))}}
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        return root


# ── installed() ───────────────────────────────────────────────────────────────
class TestInstalled(_BaseCase):
    def test_none_without_anything(self):
        self.assertIsNone(offline.installed())

    def test_whisper_pack(self):
        self._install_whisper("base")
        self.assertEqual(offline.installed(), "base")

    def test_nemotron_pack(self):
        self._install_nemotron()
        self.assertEqual(offline.installed(), "nemotron-3.5")


# ── packs() والاسم في السجل ───────────────────────────────────────────────────
class TestPacksAndLabels(_BaseCase):
    def test_three_packs_with_total_sizes(self):
        packs = {p["id"]: p["size"] for p in offline.packs()}
        self.assertEqual(sorted(packs), ["base", "nemotron-3.5", "small-q5_1"])
        # الحجم الكلي = الموديل + المحرّك
        self.assertEqual(packs["base"], offline.MODELS["base"][2] + offline.WHISPER_CPP_SIZE)
        self.assertEqual(packs["nemotron-3.5"],
                         nemotron.MODEL_SIZE + nemotron.NEMO_SPEECH_SIZE)

    def test_known_packs(self):
        self.assertEqual(offline.known_packs(), {"base", "small-q5_1", "nemotron-3.5"})

    def test_engine_label(self):
        self.assertEqual(offline.engine_label("base"), "whisper.cpp base")
        self.assertEqual(offline.engine_label("small-q5_1"), "whisper.cpp small-q5_1")
        self.assertEqual(offline.engine_label("nemotron-3.5"),
                         "nemotron-3.5-asr-streaming-0.6b")

    def test_engine_title(self):
        self.assertEqual(offline.engine_title("base"), "Whisper محلي")
        self.assertEqual(offline.engine_title("nemotron-3.5"), "Nemotron محلي")


# ── التوجيه بين المحرّكين ─────────────────────────────────────────────────────
class TestDispatch(_BaseCase):
    def test_broken_whisper_manifest_does_not_hide_nemotron_verification(self):
        self._install_whisper()
        self._install_nemotron()
        with open(offline._dirs()[3], "w", encoding="utf-8") as f:
            f.write("{")
        self.assertEqual(offline.installed(), nemotron.MODEL_ID)
        self.assertTrue(offline.verify())
        self.assertIs(offline.cached_verification(), True)

    def test_missing_whisper_file_does_not_hide_nemotron_verification(self):
        self._install_whisper()
        self._install_nemotron()
        os.remove(os.path.join(offline._dirs()[0], "whisper-cli.exe"))
        self.assertEqual(offline.installed(), nemotron.MODEL_ID)
        self.assertTrue(offline.verify())
        self.assertIs(offline.cached_verification(), True)

    def test_download_passes_a_cleared_cancel_event_to_nemotron(self):
        offline._cancel.set()
        self.addCleanup(offline._cancel.clear)

        def download(progress=None, cancel=None):
            self.assertIs(cancel, offline._cancel)
            self.assertFalse(cancel.is_set())

        with mock.patch.object(nemotron, "download", side_effect=download):
            offline.download(nemotron.MODEL_ID)

    def test_transcribe_goes_to_nemotron_when_it_is_installed(self):
        self._install_nemotron()
        with mock.patch.object(nemotron, "transcribe", return_value="نص") as tr:
            text = offline.transcribe("w.wav", "ar")
        self.assertEqual(text, "نص")
        tr.assert_called_once_with("w.wav", "ar")

    def test_transcribe_goes_to_whisper_when_it_is_installed(self):
        self._install_whisper("base")
        with mock.patch.object(offline, "_whisper_transcribe", return_value="نص") as tr:
            text = offline.transcribe("w.wav", "ar")
        self.assertEqual(text, "نص")
        tr.assert_called_once_with("w.wav", "ar")

    def test_download_nemotron_removes_the_whisper_install(self):
        self._install_whisper("base")
        with mock.patch.object(nemotron, "download") as dl:
            offline.download("nemotron-3.5")
        dl.assert_called_once()
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "offline", "models", "base.bin")))
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "offline", "manifest.json")))

    def test_download_whisper_removes_the_nemotron_install(self):
        self._install_nemotron()
        with mock.patch.object(offline, "_download_whisper") as dl:
            offline.download("base")
        dl.assert_called_once()
        self.assertFalse(os.path.exists(
            os.path.join(self._tmp.name, "offline", "nemo", "manifest.json")))

    def test_unknown_pack_raises(self):
        with self.assertRaises(ValueError):
            offline.download("nope")

    def test_remove_clears_both_engines(self):
        self._install_whisper("base")
        self._install_nemotron()
        offline.remove()
        self.assertIsNone(offline.installed())
        self.assertFalse(offline.residual())

    def test_residual_true_when_nemotron_leftovers_exist(self):
        root = os.path.join(self._tmp.name, "offline", "nemo", "models")
        os.makedirs(root)
        with open(os.path.join(root, nemotron.MODEL_FILE), "wb") as f:
            f.write(b"MODEL")
        self.assertTrue(offline.residual())


# ── سجلّ المحرّك (chains) ─────────────────────────────────────────────────────
class TestEngineReporting(_BaseCase):
    def _client(self):
        feature = {"stt": [{"provider": "local", "model": ""}], "ai": []}
        return chains.FeatureClient(feature, {}, log=lambda e, where: None)

    def test_whisper_engine_unchanged(self):
        client = self._client()
        with mock.patch.object(offline, "installed", return_value="small-q5_1"), \
                mock.patch.object(offline, "transcribe", return_value="نص"):
            client.transcribe("w.wav", None)
        self.assertEqual(client.engine(),
                         {"stt": "offline", "stt_model": "whisper.cpp small-q5_1"})

    def test_nemotron_engine_named(self):
        client = self._client()
        with mock.patch.object(offline, "installed", return_value="nemotron-3.5"), \
                mock.patch.object(offline, "transcribe", return_value="نص"):
            client.transcribe("w.wav", None)
        self.assertEqual(client.engine(),
                         {"stt": "offline", "stt_model": "nemotron-3.5-asr-streaming-0.6b"})

    def test_not_installed_refuses(self):
        client = self._client()
        with mock.patch.object(offline, "installed", return_value=None):
            with self.assertRaises(RuntimeError):
                client.transcribe("w.wav", None)


# ── واجهة الويب ──────────────────────────────────────────────────────────────
class _Ctrl:
    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []
    engine = None

    def apply_lang(self): pass
    def start_engine(self): pass
    def start_open_hotkey(self): pass
    def tk_call(self, fn): pass
    def push(self, fn, payload): pass


class TestApiOffline(_BaseCase):
    def test_status_lists_the_nemotron_pack(self):
        api = app_web.Api(_Ctrl())
        with mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            status = api.offline_status()
        ids = [m["id"] for m in status["models"]]
        self.assertIn("nemotron-3.5", ids)
        self.assertIn("base", ids)
        nemotron_pack = next(m for m in status["models"] if m["id"] == "nemotron-3.5")
        self.assertEqual(nemotron_pack["size"],
                         round((nemotron.MODEL_SIZE + nemotron.NEMO_SPEECH_SIZE) / 1_000_000))

    def test_download_accepts_the_nemotron_pack(self):
        api = app_web.Api(_Ctrl())
        started = threading.Event()

        def fake_download(model, progress=None):
            started.set()

        with mock.patch.object(offline, "download", fake_download), \
                mock.patch.object(core, "can_run", return_value=False):
            r = api.offline_download("nemotron-3.5")
        self.assertTrue(r["ok"])
        self.assertTrue(started.wait(5))

    def test_download_refuses_unknown_pack(self):
        api = app_web.Api(_Ctrl())
        r = api.offline_download("nope")
        self.assertFalse(r["ok"])
        self.assertIn("مش معروف", r["err"])

    def test_cancel_reaches_the_download(self):
        api = app_web.Api(_Ctrl())
        with mock.patch.object(offline, "cancel") as cancel:
            r = api.offline_cancel()
        self.assertTrue(r["ok"])
        cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
