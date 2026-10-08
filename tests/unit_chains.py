# -*- coding: utf-8 -*-
"""
قوائم الميزات: Client في الوضع الصارم (موديل واحد بالظبط — البديل هو العنصر الجاي في
قايمة المستخدم، مش stt_alt/chat_alt المخبّية)، وكتالوجات الموديلات، و FeatureClient
اللي بيمشي على قايمة التفريغ وقايمة المعالجة بالترتيب. مفيش شبكة ولا مفاتيح حقيقية.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402


class TestStrictClient(unittest.TestCase):
    def test_strict_stt_uses_only_the_chosen_model(self):
        cl = providers.Client("groq", "k", model="whisper-large-v3", strict=True)
        self.assertEqual(cl._stt_models(), ["whisper-large-v3"])

    def test_non_strict_keeps_todays_fallbacks(self):
        cl = providers.Client("groq", "k", model="whisper-large-v3")
        self.assertEqual(cl._stt_models(), ["whisper-large-v3", "whisper-large-v3-turbo"])

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


if __name__ == "__main__":
    unittest.main()
