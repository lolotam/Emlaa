# -*- coding: utf-8 -*-
"""
اختبارات «اقرا بصوت» (Vercel AI Gateway — TTS بس). مفيش شبكة ولا مفاتيح حقيقية:
providers._post_json متزوّد stub (حدود HTTP)، وملف .env وhistory مؤقتين.
"""
import io
import os
import sys
import base64
import tempfile
import unittest
import urllib.error
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import smart      # noqa: E402
import providers  # noqa: E402
import app_web    # noqa: E402

MP3 = b"ID3\x04\x00fake-mp3-bytes"


def _http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


def _speech(audio=MP3):
    return {"audio": base64.b64encode(audio).decode("ascii"), "warnings": []}


class TestSpeak(unittest.TestCase):
    def setUp(self):
        providers._KEY_STATE.clear()
        self.addCleanup(providers._KEY_STATE.clear)

    def test_request_contract_and_decoded_audio(self):
        cl = providers.Client("vercel", "v-key")
        with mock.patch.object(providers, "_post_json", return_value=_speech()) as post:
            self.assertEqual(cl.speak("  أهلًا  ", "google/gemini-3.8-flash-tts"), MP3)
        url, body, headers = post.call_args.args
        self.assertEqual(url, "https://ai-gateway.vercel.sh/v4/ai/speech-model")
        self.assertEqual(body, {"text": "أهلًا", "outputFormat": "mp3"})
        self.assertEqual(headers, {"Authorization": "Bearer v-key",
                                   "ai-model-id": "google/gemini-3.8-flash-tts",
                                   "ai-gateway-protocol-version": "0.0.1",
                                   "ai-speech-model-specification-version": "4"})

    def test_bad_input_is_refused_before_any_request(self):
        cl = providers.Client("vercel", "v-key")
        cases = [("", "openai/tts-1", "مفيش نص يتقري"),
                 ("x" * (providers.TTS_MAX_CHARS + 1), "openai/tts-1", "النص أطول من 4000 حرف"),
                 ("أهلًا", "openai/whisper-1", "موديل الصوت مش معروف")]
        for text, model, err in cases:
            with self.subTest(err=err), mock.patch.object(providers, "_post_json") as post:
                with self.assertRaises(RuntimeError) as cm:
                    cl.speak(text, model)
                self.assertEqual(str(cm.exception), err)
                post.assert_not_called()

    def test_missing_or_corrupt_audio_is_an_error(self):
        cl = providers.Client("vercel", "v-key")
        for reply in ({"warnings": []}, {"audio": "QUJD!!"}, {"audio": ""}):
            with self.subTest(reply=reply), \
                    mock.patch.object(providers, "_post_json", return_value=reply):
                with self.assertRaises(RuntimeError) as cm:
                    cl.speak("أهلًا", "openai/tts-1")
                self.assertEqual(str(cm.exception), "الخدمة مارجّعتش صوت")

    def test_rejected_key_switches_to_the_next_key(self):
        cl = providers.Client("vercel", keys=["bad", "good"])
        with mock.patch.object(providers, "_post_json",
                               side_effect=[_http_error(401), _speech()]) as post:
            self.assertEqual(cl.speak("أهلًا", "openai/tts-1"), MP3)
        self.assertEqual([c.args[2]["Authorization"] for c in post.call_args_list],
                         ["Bearer bad", "Bearer good"])

    def test_network_failure_becomes_network_error(self):
        cl = providers.Client("vercel", "v-key")
        with mock.patch.object(providers, "_post_json",
                               side_effect=urllib.error.URLError("dns fail")):
            with self.assertRaises(providers.NetworkError):
                cl.speak("أهلًا", "openai/tts-1")


class TestHelpers(unittest.TestCase):
    def test_audio_mime_from_magic_bytes(self):
        for data, mime in ((b"RIFF....WAVE", "audio/wav"), (b"OggS....", "audio/ogg"),
                           (MP3, "audio/mpeg")):
            with self.subTest(mime=mime):
                self.assertEqual(providers.audio_mime(data), mime)

    def test_error_messages_for_the_user(self):
        cases = [(providers.NetworkError("dns"), "مفيش اتصال بالنت — اتأكد من الاتصال وجرّب تاني"),
                 (RuntimeError("HTTP 401: bad"), "مفتاح Vercel AI Gateway مش مقبول"),
                 (RuntimeError("HTTP 429: slow down"), "رصيد Vercel AI Gateway خلص أو وصلت للحد"),
                 (RuntimeError("موديل الصوت مش معروف"), "موديل الصوت مش معروف"),
                 (RuntimeError("HTTP 500: boom"), "مقدرتش أقرا النص — HTTP 500: boom")]
        for e, msg in cases:
            with self.subTest(msg=msg):
                self.assertEqual(providers.tts_error_message(e), msg)


class _Ctrl:
    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []
    engine = None
    window = None

    def start_engine(self):
        pass

    def apply_lang(self):
        pass

    def start_open_hotkey(self):
        pass

    def tk_call(self, fn):
        pass


class TestAppWebTts(unittest.TestCase):
    """واجهة الـPython للصفحة: bootstrap و save_settings و history_speak."""

    def setUp(self):
        providers._KEY_STATE.clear()
        self.addCleanup(providers._KEY_STATE.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env_path = os.path.join(tmp.name, ".env")
        for p in (mock.patch.object(core, "ENV_PATH", self.env_path),
                  mock.patch.object(core, "CFG", dict(core.DEFAULTS)),
                  mock.patch.object(core, "save_config"),
                  mock.patch.object(core, "log_error"),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.api = app_web.Api(_Ctrl())

    def _keys(self, text):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(text)

    def _entry(self, **item):
        return mock.patch.object(core, "history_entry", return_value=item)

    def test_bootstrap_lists_vercel_as_tts_only(self):
        self._keys("AI_GATEWAY_API_KEY=v-key\n")
        with mock.patch.object(core, "history_stats", return_value={}):
            boot = self.api.bootstrap()
        vercel = [p for p in boot["providers"] if p["id"] == "vercel"]
        self.assertEqual([(p["tts"], p["hasKey"]) for p in vercel], [(True, True)])
        self.assertFalse(any(p["tts"] for p in boot["providers"] if p["id"] != "vercel"))
        self.assertNotIn("vercel", boot["catalog"])           # مش في قوايم التفريغ/المعالجة
        self.assertEqual(boot["ttsModels"], providers.TTS_MODELS["vercel"])
        self.assertEqual(boot["cfg"]["tts_model"], "openai/tts-1")

    def test_vercel_is_not_a_transcription_choice(self):
        stt = [{"provider": "vercel", "model": "openai/tts-1"}]
        features = {m: {"hotkey": [0x70 + i], "stt": stt, "ai": []}
                    for i, m in enumerate(smart.FEATURES)}
        self.assertEqual(smart.validate_features(features), "مزوّد تفريغ مش معروف")
        self.assertEqual(self.api._store_welcome_key("vercel", "v-key"), "مزوّد مش معروف")

    def test_removing_the_only_vercel_key_is_allowed_without_any_stt_key(self):
        self._keys("AI_GATEWAY_API_KEY=v-key\n")
        r = self.api.key_remove("vercel", 0)
        self.assertTrue(r["ok"], r)
        self.assertEqual(providers.read_key_pools(self.env_path), {})

    def test_save_settings_keeps_only_known_tts_models(self):
        with mock.patch.object(core, "history_stats", return_value={}):
            self.api.save_settings({"tts_model": "spacexai/grok-tts"})
            self.assertEqual(core.CFG["tts_model"], "spacexai/grok-tts")
            self.api.save_settings({"tts_model": "evil/model"})
        self.assertEqual(core.CFG["tts_model"], "spacexai/grok-tts")

    def test_history_speak_returns_playable_audio_with_the_chosen_model(self):
        self._keys("AI_GATEWAY_API_KEY=v-key\n")
        core.CFG["tts_model"] = "microsoft/mai-voice-2.1"
        with self._entry(result="النص النهائي", status="ok"), \
                mock.patch.object(providers, "_post_json", return_value=_speech()) as post:
            r = self.api.history_speak(7)
        self.assertEqual(r, {"ok": True, "mime": "audio/mpeg",
                             "data": base64.b64encode(MP3).decode("ascii")})
        self.assertEqual(post.call_args.args[1]["text"], "النص النهائي")
        self.assertEqual(post.call_args.args[2]["ai-model-id"], "microsoft/mai-voice-2.1")

    def test_history_speak_falls_back_to_default_for_a_stale_saved_model(self):
        self._keys("AI_GATEWAY_API_KEY=v-key\n")
        core.CFG["tts_model"] = "removed/old-voice"          # config قديم أو متعدّل يدوي
        with self._entry(result="نص", status="ok"), \
                mock.patch.object(providers, "_post_json", return_value=_speech()) as post:
            self.assertTrue(self.api.history_speak(7)["ok"])
        self.assertEqual(post.call_args.args[2]["ai-model-id"], "openai/tts-1")

    def test_history_speak_refuses_without_key_or_text(self):
        cases = [("", dict(result="نص", status="ok"), "ضيف مفتاح Vercel AI Gateway الأول"),
                 ("AI_GATEWAY_API_KEY=v-key\n", dict(result="", status="ok"), "مفيش نص يتقري"),
                 ("AI_GATEWAY_API_KEY=v-key\n", dict(result="نص", status="failed"), "مفيش نص يتقري")]
        for env, item, err in cases:
            with self.subTest(err=err, item=item):
                self._keys(env)
                with self._entry(**item), mock.patch.object(providers, "_post_json") as post:
                    self.assertEqual(self.api.history_speak(7), {"ok": False, "err": err})
                post.assert_not_called()

    def test_history_speak_reports_provider_failure_in_arabic(self):
        self._keys("AI_GATEWAY_API_KEY=v-key\n")
        with self._entry(result="نص", status="ok"), \
                mock.patch.object(providers, "_post_json", side_effect=_http_error(401)):
            r = self.api.history_speak(7)
        self.assertEqual(r, {"ok": False, "err": "مفتاح Vercel AI Gateway مش مقبول"})
        core.log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
