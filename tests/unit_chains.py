# -*- coding: utf-8 -*-
"""
قوائم الميزات: Client في الوضع الصارم (موديل واحد بالظبط — البديل هو العنصر الجاي في
قايمة المستخدم، مش stt_alt/chat_alt المخبّية)، وكتالوجات الموديلات، و FeatureClient
اللي بيمشي على قايمة التفريغ وقايمة المعالجة بالترتيب. مفيش شبكة ولا مفاتيح حقيقية.
"""
import io
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402
import chains     # noqa: E402


def _feature(stt=(), ai=()):
    return {"hotkey": [], "stt": [dict(i) for i in stt], "ai": [dict(i) for i in ai]}


class TestDefaultFactoryIsStrictAtTheHttpBoundary(unittest.TestCase):
    """
    FeatureClient من غير client_factory = العملاء الحقيقيين. البديل الوحيد هو العنصر الجاي في
    قايمة المستخدم: الموديل اللي ردّ 404 مايتبدّلش بـstt_alt/chat_alt المخبّية.
    """

    def setUp(self):
        providers._KEY_STATE.clear()
        self.addCleanup(providers._KEY_STATE.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wav = os.path.join(tmp.name, "a.wav")
        with open(self.wav, "wb") as f:
            f.write(b"RIFF")

    def deepgram_models_requested(self, client):
        seen = []

        def urlopen(req, **kw):
            seen.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(req.full_url).query))["model"])
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, io.BytesIO(b"{}"))

        with mock.patch.object(providers.urllib.request, "urlopen", side_effect=urlopen), \
                mock.patch("core.log_error"), self.assertRaises(Exception):
            client.transcribe(self.wav)
        return seen

    def test_feature_stt_tries_only_the_listed_model(self):
        fc = chains.FeatureClient(_feature(stt=[{"provider": "deepgram", "model": "nova-3"}]), {"deepgram": ["d"]})
        self.assertEqual(self.deepgram_models_requested(fc), ["nova-3"])

    def test_non_strict_client_would_fall_back_to_hidden_models(self):
        # المقارنة: نفس الـ404 في Client العادي بيجرّب stt_alt — يعني الاختبار اللي فوق بيفرّق فعلًا
        cl = providers.Client("deepgram", "d", model="nova-3")
        self.assertEqual(self.deepgram_models_requested(cl), ["nova-3", "whisper-large"])

    def test_feature_ai_tries_only_the_listed_model(self):
        fc = chains.FeatureClient(_feature(stt=[{"provider": "gemini", "model": "gemini-3.8-flash"}],
                                           ai=[{"provider": "gemini", "model": "gemini-3.5-flash"}]),
                                  {"gemini": ["g"]})
        seen = []

        def post(url, payload, hdr):
            seen.append(url.split("/models/")[1].split(":")[0])
            raise RuntimeError("HTTP 404: not found")

        with mock.patch.object(providers, "_post_json", side_effect=post), mock.patch("core.log_error"):
            fc._chat_raw("sys", "نص")
        self.assertEqual(seen, ["gemini-3.5-flash"])
        self.assertFalse(fc.ai_ok)


class TestStrictClient(unittest.TestCase):

    def test_strict_chat_does_not_walk_chat_alt(self):
        cl = providers.Client("groq", "k", strict=True, chat_model="openai/gpt-oss-20b")
        seen = []

        def create(**kw):
            seen.append(kw["model"])
            raise RuntimeError("model_not_found")

        fake = mock.Mock()
        fake.with_options.return_value.chat.completions.create.side_effect = create
        with mock.patch.object(cl, "_openai", return_value=fake), mock.patch("core.log_error"):
            self.assertIsNone(cl._chat_raw("sys", "نص"))
        self.assertEqual(seen, ["openai/gpt-oss-20b"])

    def test_strict_gemini_chat_uses_only_the_chosen_model(self):
        cl = providers.Client("gemini", "k", strict=True, chat_model="gemini-3.5-flash")
        seen = []

        def post(url, payload, hdr):
            seen.append(url.split("/models/")[1].split(":")[0])
            raise RuntimeError("HTTP 404: not found")

        with mock.patch.object(providers, "_post_json", side_effect=post), mock.patch("core.log_error"):
            self.assertIsNone(cl._chat_raw("sys", "نص"))
        self.assertEqual(seen, ["gemini-3.5-flash"])

    def test_strict_chat_on_stt_only_provider_fails_instead_of_borrowing_helper(self):
        helper = mock.Mock()
        cl = providers.Client("deepgram", "k", strict=True, helper=helper)
        with mock.patch("core.log_error"):
            self.assertIsNone(cl._chat_raw("sys", "نص"))
        helper._chat_raw.assert_not_called()


class TestCatalogs(unittest.TestCase):
    def test_chat_models(self):
        self.assertEqual(providers.chat_models("deepgram"), [])
        self.assertEqual(providers.chat_models("groq")[0], providers.PROVIDERS["groq"]["chat"])
        self.assertIn(providers.PROVIDERS["groq"]["chat_alt"][0], providers.chat_models("groq"))

    def test_stt_order_follows_todays_choice(self):
        self.assertEqual(providers.stt_order("groq", "whisper-large-v3")[0], "whisper-large-v3")
        self.assertEqual(providers.stt_order("groq"), ["whisper-large-v3-turbo", "whisper-large-v3"])

    def test_stt_catalog_lists_every_pickable_model(self):
        self.assertEqual(providers.stt_catalog("openai")[:3],
                         ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"])
        self.assertIn("whisper-1", providers.stt_catalog("openai"))


class FakeProv:
    def __init__(self, pid, model, chat_model, fail=None):
        self.pid, self.model, self.chat_model, self.fail = pid, model, chat_model, fail
        self.vocab, self.vocab_extra, self.last_stt_model = [], [], None
        self.seen_vocab = None

    def transcribe(self, wav, lang):
        self.seen_vocab = (list(self.vocab), list(self.vocab_extra))
        if self.fail:
            raise self.fail
        self.last_stt_model = self.model
        return "نص:" + self.pid + ":" + self.model

    def _chat_raw(self, system, text, temperature=0.2):
        if self.fail:
            raise self.fail
        return "AI:" + self.pid + ":" + self.chat_model


def build(feature, fails=None, pools=None):
    """fails: {pid: exc} أو {(pid, model): exc} — made بيسجّل كل عميل اتبنى بترتيبه."""
    fails, made = fails or {}, []
    pools = pools if pools is not None else {"groq": ["k"], "gemini": ["k"], "deepgram": ["k"]}

    def factory(pid, keys, model, chat_model):
        made.append(pid)
        return FakeProv(pid, model, chat_model, fails.get((pid, model or chat_model), fails.get(pid)))

    return chains.FeatureClient(feature, pools, client_factory=factory, log=lambda e, where: None), made


FEAT = {"hotkey": [], "stt": [{"provider": "deepgram", "model": "nova-3"}, {"provider": "groq", "model": "w"}],
        "ai": [{"provider": "groq", "model": "q"}, {"provider": "gemini", "model": "g"}]}


class TestStt(unittest.TestCase):
    def test_first_item_serves(self):
        fc, _ = build(FEAT)
        self.assertEqual(fc.transcribe("w.wav", None), "نص:deepgram:nova-3")
        self.assertEqual(fc.engine(), {"stt": "Deepgram", "stt_model": "nova-3"})

    def test_next_item_on_any_error(self):
        fc, made = build(FEAT, fails={"deepgram": RuntimeError("HTTP 429")})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:w")
        self.assertEqual(made, ["deepgram", "groq"])

    def test_missing_key_skips_without_client(self):
        fc, made = build(FEAT, pools={"groq": ["k"]})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:w")
        self.assertEqual(made, ["groq"])

    def test_same_provider_two_models_in_order(self):
        feat = dict(FEAT, stt=[{"provider": "groq", "model": "a"}, {"provider": "groq", "model": "b"}],
                    ai=[{"provider": "groq", "model": "q1"}, {"provider": "groq", "model": "q2"}])
        fc, _ = build(feat, fails={("groq", "a"): RuntimeError("404"), ("groq", "q1"): RuntimeError("404")})
        self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:b")
        self.assertEqual(fc._chat("sys", "نص"), "AI:groq:q2")
        self.assertEqual((fc.engine()["stt_model"], fc.engine()["chat_model"]), ("b", "q2"))

    def test_network_error_preferred_when_all_fail(self):
        fc, _ = build(FEAT, fails={"deepgram": providers.NetworkError("dns"),
                                   "groq": RuntimeError("HTTP 401")})
        with self.assertRaises(providers.NetworkError):
            fc.transcribe("w.wav", None)

    def test_last_error_raised_when_no_network_error(self):
        fc, _ = build(FEAT, fails={"deepgram": RuntimeError("HTTP 429"), "groq": RuntimeError("HTTP 401")})
        with self.assertRaisesRegex(RuntimeError, "401"):
            fc.transcribe("w.wav", None)

    def test_local_first_builds_no_provider_client(self):
        feat = dict(FEAT, stt=[{"provider": "local", "model": ""}, {"provider": "groq", "model": "w"}])
        fc, made = build(feat)
        with mock.patch.object(chains.offline, "installed", return_value="base"), \
                mock.patch.object(chains.offline, "transcribe", return_value="محلي"):
            self.assertEqual(fc.transcribe("w.wav", None), "محلي")
        self.assertEqual((made, fc.stt_local), ([], True))
        self.assertEqual(fc.engine(), {"stt": "offline", "stt_model": "whisper.cpp base"})

    def test_local_not_installed_moves_on(self):
        feat = dict(FEAT, stt=[{"provider": "local", "model": ""}, {"provider": "groq", "model": "w"}])
        fc, _ = build(feat)
        with mock.patch.object(chains.offline, "installed", return_value=None):
            self.assertEqual(fc.transcribe("w.wav", None), "نص:groq:w")
        self.assertFalse(fc.stt_local)

    def test_vocab_reaches_provider_client_every_operation(self):
        fc, _ = build(FEAT)
        fc.vocab, fc.vocab_extra = ["Next.js"], ["إيميلي"]
        fc.transcribe("w.wav", None)
        fc.vocab = ["Docker"]
        fc.transcribe("w.wav", None)
        self.assertEqual(fc._clients_for_test()[0].seen_vocab, (["Docker"], ["إيميلي"]))


class TestAi(unittest.TestCase):
    def test_ai_order_and_ok_flag(self):
        fc, _ = build(FEAT, fails={"groq": RuntimeError("HTTP 429")})
        fc.transcribe("w.wav", None)
        self.assertEqual(fc._chat("sys", "نص"), "AI:gemini:g")
        self.assertTrue(fc.ai_ok)
        self.assertEqual(fc.last_chat, ("Google Gemini", "g"))

    def test_all_fail(self):
        fc, _ = build(FEAT, fails={"groq": RuntimeError("x"), "gemini": RuntimeError("y")})
        fc.transcribe("w.wav", None)
        self.assertEqual(fc._chat("sys", "نص"), "نص")
        self.assertIsNone(fc._chat_raw("sys", "نص"))
        self.assertFalse(fc.ai_ok)
        self.assertIsNone(fc.last_chat)

    def test_ai_ok_survives_a_later_failed_call(self):
        # to_prompt بيحتفظ بأول رد لو إعادة اللغة فشلت — ده لسه رد AI
        fc, _ = build(FEAT)
        fc.transcribe("w.wav", None)
        fc._chat("sys", "نص")
        fc._ai_items_for_test().clear()
        self.assertIsNone(fc._chat_raw("sys", "نص"))
        self.assertTrue(fc.ai_ok)

    def test_state_reset_between_operations(self):
        fc, _ = build(FEAT)
        fc.transcribe("w.wav", None)
        fc._chat("sys", "نص")
        self.assertIsNotNone(fc.last_chat)
        fc.transcribe("w.wav", None)
        self.assertIsNone(fc.last_chat)
        self.assertFalse(fc.ai_ok)

    def test_empty_ai_list_returns_text(self):
        fc, made = build(dict(FEAT, ai=[]))
        self.assertEqual(fc._chat("sys", "نص"), "نص")
        self.assertIsNone(fc._chat_raw("sys", "نص"))
        self.assertEqual(made, [])


if __name__ == "__main__":
    unittest.main()
