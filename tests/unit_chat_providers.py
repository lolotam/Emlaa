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

import chains     # noqa: E402
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
            # شكل قايمة MiMo الموثّقة (list-models): موديلات التفريغ والصوت جنب الشات من غير نوع
            ("xiaomi", {"object": "list", "data": [{"id": "mimo-v2.6-flash", "object": "model", "owned_by": "xiaomi"},
                                                   {"id": "mimo-v2.5-asr"}, {"id": "mimo-v2.5-tts-voiceclone"},
                                                   {"id": "mimo-v2.6-pro"}]},
             ["mimo-v2.6-flash", "mimo-v2.6-pro"]),
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
        thinking_off = {"extra_body": {"thinking": {"type": "disabled"}}}
        for pid, url, model, extra in (
                ("xai", "https://api.x.ai/v1", "grok-4.7", {}),
                ("openrouter", "https://openrouter.ai/api/v1", "google/gemini-3.8-flash", {}),
                ("zai_coding", "https://api.z.ai/api/coding/paas/v4", "glm-5.3", thinking_off),
                ("xiaomi", "https://token-plan-sgp.xiaomimimo.com/v1", "mimo-v2.6-flash", thinking_off)):
            fake = mock.MagicMock()
            fake.with_options.return_value.chat.completions.create.return_value.choices = [
                mock.Mock(message=mock.Mock(content="Hello there"))]
            with self.subTest(pid=pid), mock.patch("openai.OpenAI", return_value=fake) as ctor:
                self.assertEqual(providers.Client(pid, "k-1").translate("أهلًا يا جماعة"), "Hello there")
            self.assertEqual(ctor.call_args.kwargs["base_url"], url)
            self.assertEqual(ctor.call_args.kwargs["api_key"], "k-1")
            sent = fake.with_options.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(sent["model"], model)
            self.assertEqual({k: v for k, v in sent.items() if k == "extra_body"}, extra)

    def test_simulated_temperature_rejection_falls_back_to_the_next_item(self):
        # الرفض هنا متخيّل — مش سلوك اتشاف: OpenRouter موثّق إنه بيتجاهل البارامتر اللي المزوّد
        # مبيدعموش (require_parameters=false)، وClaude 5.5 مفيهوش temperature في supported_parameters
        # (قايمة /models العامة، أكتوبر ٢٠٢٦). الاختبار بيثبّت إن لو جه 400 بدل التجاهل، العنصر
        # الجاي في قايمة الميزة هو اللي يرد — مش النص الخام. رسالة الخطأ تأليف للاختبار
        import httpx
        import openai
        sent = []

        def create(**kw):
            sent.append((kw["model"], kw["temperature"]))
            if kw["model"].startswith("anthropic/"):
                req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
                raise openai.BadRequestError("temperature: must be 1", response=httpx.Response(400, request=req),
                                             body=None)
            return mock.Mock(choices=[mock.Mock(message=mock.Mock(content="Hello there"))])

        fake = mock.MagicMock()
        fake.with_options.return_value.chat.completions.create.side_effect = create
        feature = {"hotkey": [], "stt": [], "ai": [{"provider": "openrouter", "model": "anthropic/claude-haiku-5.5"},
                                                  {"provider": "openrouter", "model": "x-ai/grok-4.7"}]}
        fc = chains.FeatureClient(feature, {"openrouter": ["sk-or-1"]}, log=lambda e, where: None)
        with mock.patch("openai.OpenAI", return_value=fake), mock.patch("core.log_error"):
            self.assertEqual(fc.translate("أهلًا يا جماعة"), "Hello there")
        self.assertEqual(sent, [("anthropic/claude-haiku-5.5", 0.2), ("x-ai/grok-4.7", 0.2)])
        self.assertEqual(fc.last_chat, ("OpenRouter", "x-ai/grok-4.7"))

    def test_new_chat_providers_are_accepted_in_the_processing_list(self):
        stt = [{"provider": "groq", "model": "whisper-large-v3-turbo"}]
        for pid in ("xai", "openrouter"):
            features = {m: {"hotkey": [0x70 + i], "stt": stt, "ai": [{"provider": pid, "model": "any/live-model"}]}
                        for i, m in enumerate(smart.FEATURES)}
            with self.subTest(pid=pid):
                self.assertIsNone(smart.validate_features(features))

    def test_chat_only_providers_are_refused_in_the_transcription_list(self):
        for pid in providers.CHAT_ONLY_ORDER:
            features = {m: {"hotkey": [0x70 + i], "stt": [{"provider": pid, "model": "x"}],
                            "ai": [{"provider": pid, "model": "x"}]}
                        for i, m in enumerate(smart.FEATURES)}
            with self.subTest(pid=pid):
                self.assertEqual(smart.validate_features(features), "مزوّد تفريغ مش معروف")
                features = {m: dict(f, stt=[{"provider": "groq", "model": "whisper-large-v3-turbo"}])
                            for m, f in features.items()}
                self.assertIsNone(smart.validate_features(features))

    def test_chat_only_list_matches_providers_without_a_transcription_model(self):
        # نفس سبب STT_ONLY: smart مبيقدرش يستورد providers
        self.assertEqual(smart.CHAT_ONLY, tuple(providers.CHAT_ONLY_ORDER))
        self.assertEqual({p for p in providers.PROVIDERS if providers.PROVIDERS[p]["chat"]
                          and not providers.PROVIDERS[p]["stt"]}, set(providers.CHAT_ONLY_ORDER))

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
        pids = providers.ORDER + providers.CHAT_ONLY_ORDER
        self.assertEqual({p for p in pids if catalog[p]["liveModels"]},
                         {"groq", "xai", "openrouter", "zai_coding", "xiaomi"})
        self.assertEqual({p for p in pids if catalog[p]["chatOnly"]}, {"zai_coding", "xiaomi"})
        self.assertFalse(catalog["xai"]["sttOnly"])
        self.assertEqual(catalog["xiaomi"]["sttModels"], [])


class TestVerifyChatOnly(unittest.TestCase):
    """التأكد من مفتاح Z.ai Coding Plan و Xiaomi: /models ببلاش، ولو مش موجودة رد بتوكن واحد."""

    def setUp(self):
        providers._KEY_STATE.clear()
        self.addCleanup(providers._KEY_STATE.clear)

    def test_key_works_when_the_model_list_answers_without_any_paid_request(self):
        for pid, key in (("zai_coding", "z-1"), ("xiaomi", "tp-1")):
            with self.subTest(pid=pid), mock.patch.object(providers, "_get_json", return_value={"data": []}) as get,                     mock.patch.object(providers, "_post_json") as post:
                self.assertEqual(providers.verify(pid, key), (True, ""))
            self.assertEqual(get.call_args.args, (providers.PROVIDERS[pid]["base_url"] + "/models",
                                                  {"Authorization": "Bearer " + key}))
            post.assert_not_called()

    def test_missing_model_list_falls_back_to_a_one_token_reply(self):
        # PR #22 (MergePilot): أي رد غير رفض المفتاح على /models — مش 404 بس — بيكمّل للرد
        for list_err in (_http_error(404), _http_error(405), _http_error(501), ValueError("not json")):
            with self.subTest(err=list_err), mock.patch.object(providers, "_get_json", side_effect=list_err),                     mock.patch.object(providers, "_post_json", return_value={"choices": []}) as post:
                self.assertEqual(providers.verify("xiaomi", "ttp-1"), (True, ""))
        url, body, headers = post.call_args.args
        self.assertEqual(url, "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions")
        self.assertEqual((body["model"], body["max_tokens"], body["thinking"]), ("mimo-v2.6-flash", 1, {"type": "disabled"}))
        self.assertEqual(headers, {"Authorization": "Bearer ttp-1"})

    def test_probe_request_shape_rejected_still_means_the_key_works(self):
        # 400 على رد التوكن الواحد (مثلًا max_tokens مش مقبول) = المفتاح عدّى؛ 401 = مرفوض
        cases = [(_http_error(400), (True, "")), (_http_error(401), (False, "المفتاح مش مقبول — اتأكد إنك نسخته كامل"))]
        for probe_err, expected in cases:
            with self.subTest(code=probe_err.code),                     mock.patch.object(providers, "_get_json", side_effect=_http_error(404)),                     mock.patch.object(providers, "_post_json", side_effect=probe_err):
                self.assertEqual(providers.verify("zai_coding", "z-1"), expected)

    def test_rejected_key_fails_without_a_paid_request(self):
        cases = [("zai_coding", "z-1", _http_error(401), "المفتاح مش مقبول — اتأكد إنك نسخته كامل"),
                 ("zai_coding", "z-1", _http_error(429), "المفتاح شغّال بس الرصيد/الحد خلص"),
                 ("xiaomi", "sk-payg", None, "مفتاح Token Plan بيبدأ بحروف tp أو ttp — اتأكد إنك نسخته كامل")]
        for pid, key, err, msg in cases:
            with self.subTest(pid=pid), mock.patch.object(providers, "_get_json", side_effect=err) as get,                     mock.patch.object(providers, "_post_json") as post:
                self.assertEqual(providers.verify(pid, key), (False, msg))
            post.assert_not_called()
            if err is None:
                get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
