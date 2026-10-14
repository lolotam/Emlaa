# -*- coding: utf-8 -*-
"""
معالجة النص بـxAI و OpenRouter وقايمة موديلاتهم الحيّة. مفيش شبكة ولا مفاتيح حقيقية:
providers._get_json (قايمة /models) و openai.OpenAI (نداء الشات) متزوّدين stub.
"""
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import smart      # noqa: E402
import providers  # noqa: E402
import app_web    # noqa: E402
from unit_tts import _Ctrl  # noqa: E402

# شكل رد OpenRouter الحقيقي (GET /api/v1/models العام، أكتوبر ٢٠٢٦) مختصر
OPENROUTER_MODELS = {"data": [
    {"id": "anthropic/claude-haiku-5.5", "architecture": {"output_modalities": ["text"]}},
    {"id": "anthropic/claude-haiku-5.5:batch", "architecture": {"output_modalities": ["text"]}},
    {"id": "google/gemini-nano-banana-2.1", "architecture": {"output_modalities": ["image", "text"]}},
    {"id": "x-ai/grok-4.7", "architecture": {"output_modalities": ["text"]}},
    {"id": "liquid/lfm-2.5-2.6b:free", "architecture": {"output_modalities": ["text"]}},
]}


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b"{}"))


class TestLiveChatModels(unittest.TestCase):
    def test_list_keeps_only_models_the_chat_call_can_use(self):
        cases = [
            ("openrouter", OPENROUTER_MODELS,
             ["anthropic/claude-haiku-5.5", "x-ai/grok-4.7", "liquid/lfm-2.5-2.6b:free"]),
            # قايمة بتكتب النوع (زي البوابات) وقايمة مبتكتبهوش (Groq: موديلات التفريغ جنب الشات)
            ("xai", {"data": [{"id": "grok-4.7", "type": "language"}, {"id": "grok-imagine", "type": "image"},
                              {"id": "grok-voice-transcribe-2.0"}, {"id": "grok-4.7"}]},
             ["grok-4.7"]),
            ("groq", {"data": [{"id": "whisper-large-v3"}, {"id": "qwen/qwen3.8-27b"},
                               {"id": "nomic-embed-text"}, {"id": "playai-tts"},
                               {"id": "canopylabs/orpheus-v1-english"}, {"id": "meta-llama/llama-guard-4-12b"},
                               {"id": "openai/gpt-oss-safeguard-20b"}]},
             ["qwen/qwen3.8-27b"]),
        ]
        for pid, body, expected in cases:
            with self.subTest(pid=pid), mock.patch.object(providers, "_get_json", return_value=body) as get:
                self.assertEqual(providers.list_chat_models(pid, "k-1"), expected)
            url, headers = get.call_args.args
            self.assertEqual(url, providers.PROVIDERS[pid]["base_url"] + "/models")
            self.assertEqual(headers, {"Authorization": "Bearer k-1"})


class TestChatThroughNewProviders(unittest.TestCase):
    def setUp(self):
        providers._KEY_STATE.clear()
        self.addCleanup(providers._KEY_STATE.clear)

    def test_chat_goes_to_the_provider_endpoint_with_its_first_model(self):
        for pid, url, model in (("xai", "https://api.x.ai/v1", "grok-4.7"),
                                ("openrouter", "https://openrouter.ai/api/v1", "google/gemini-3.8-flash")):
            fake = mock.MagicMock()
            fake.with_options.return_value.chat.completions.create.return_value.choices = [
                mock.Mock(message=mock.Mock(content="Hello there"))]
            with self.subTest(pid=pid), mock.patch("openai.OpenAI", return_value=fake) as ctor:
                self.assertEqual(providers.Client(pid, "k-1").translate("أهلًا يا جماعة"), "Hello there")
            self.assertEqual(ctor.call_args.kwargs["base_url"], url)
            self.assertEqual(ctor.call_args.kwargs["api_key"], "k-1")
            self.assertEqual(fake.with_options.return_value.chat.completions.create.call_args.kwargs["model"], model)

    def test_new_chat_providers_are_accepted_in_the_processing_list(self):
        stt = [{"provider": "groq", "model": "whisper-large-v3-turbo"}]
        for pid in ("xai", "openrouter"):
            features = {m: {"hotkey": [0x70 + i], "stt": stt, "ai": [{"provider": pid, "model": "any/live-model"}]}
                        for i, m in enumerate(smart.FEATURES)}
            with self.subTest(pid=pid):
                self.assertIsNone(smart.validate_features(features))

    def test_stt_only_list_matches_providers_without_a_chat_model(self):
        # smart مبيقدرش يستورد providers (providers بيستورد smart) — فالقايمتين لازم يتطابقوا هنا
        self.assertEqual(set(smart.STT_ONLY) - {smart.LOCAL},
                         {p for p in providers.ORDER if not providers.PROVIDERS[p]["chat"]})


class TestChatModelsLiveApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env_path = os.path.join(tmp.name, ".env")
        for p in (mock.patch.object(core, "ENV_PATH", self.env_path),
                  mock.patch.object(core, "CFG", dict(core.DEFAULTS)),
                  mock.patch.object(core, "log_error"),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.api = app_web.Api(_Ctrl())

    def _keys(self, text):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_models_come_from_the_provider_with_its_stored_key(self):
        self._keys("OPENROUTER_API_KEY=sk-or-1,sk-or-2\n")
        with mock.patch.object(providers, "_get_json", return_value=OPENROUTER_MODELS) as get:
            r = self.api.chat_models_live("openrouter")
        self.assertEqual(r["ok"], True)
        self.assertIn("x-ai/grok-4.7", r["models"])
        self.assertEqual(get.call_args.args[1], {"Authorization": "Bearer sk-or-1"})

    def test_no_request_without_a_key_or_for_a_provider_without_a_list(self):
        self._keys("GEMINI_API_KEY=g-1\n")
        cases = [("xai", "ضيف مفتاح للمزوّد ده الأول"),
                 ("gemini", "المزوّد ده مبيعرضش موديلاته"),
                 ("deepgram", "المزوّد ده مبيعرضش موديلاته")]
        for pid, err in cases:
            with self.subTest(pid=pid), mock.patch.object(providers, "_get_json") as get:
                self.assertEqual(self.api.chat_models_live(pid), {"ok": False, "err": err})
            get.assert_not_called()

    def test_failed_list_is_logged_and_keeps_the_fixed_list(self):
        self._keys("XAI_API_KEY=xai-1\n")
        with mock.patch.object(providers, "_get_json", side_effect=_http_error(401)):
            r = self.api.chat_models_live("xai")
        self.assertEqual(r, {"ok": False, "err": "مقدرتش أجيب قايمة الموديلات — القايمة الثابتة لسه موجودة"})
        core.log_error.assert_called_once()

    def test_catalog_marks_which_providers_have_a_live_list(self):
        catalog = app_web._feature_catalog({}, None)
        self.assertEqual({p for p in providers.ORDER if catalog[p]["liveModels"]}, {"groq", "xai", "openrouter"})
        self.assertFalse(catalog["xai"]["sttOnly"])


if __name__ == "__main__":
    unittest.main()
