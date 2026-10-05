# -*- coding: utf-8 -*-
"""
اختبارات F2 — لغة البرومبت: الطلب الإنجليزي بيتقرر محليًا (smart.prompt_language)،
وأي طلب عربي أو مخلوط بيتقرر بتصنيف الموديل TECH/OTHER (providers._prompt_lang) حسب
اللي المستخدم عايز يطلّعه، والكلمات التقنية (smart.tech_guess) تخمين احتياطي بس لو
التصنيف فشل. الـdirective بيتضاف للنظام، والإعادة مرة واحدة لو الموديل رد باللغة الغلط.
مفيش شبكة ولا مفاتيح: _chat و_chat_raw متزوّدين fake، والمخرجات ثابتة.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart      # noqa: E402
import providers  # noqa: E402


# ── prompt_language: الإنجليزي محلي، والعربي/المخلوط كله للتصنيف ─────────────────
# الكلمة التقنية مبتقررش لوحدها: «اكتب إعلان لدورة Python» و«اكتب رسالة فيها كود
# خصم» طلبات كتابة مش برمجة — فحتى الطلب العربي اللي فيه «داتابيز» بيروح للتصنيف.
ARABIC_OR_MIXED = [
    "ظبط الداتابيز دي", "عايز ابليكيشن للسوبر ماركت", "اعمل الويب سايت بتاعي",
    "اكتب إعلانًا لدورة Python", "عايز API للدفع", "اكتب لي برنامج غذائي لزيادة الوزن",
    "اشرح تطبيق القانون", "ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين",
    "اكتب رسالة للعميل فيها discount code للطلب الجاي", "اكتب script لإعلان عطر جديد",
    "اكتب رسالة شكر لمديري", "ويبقى الكلام ده بينا",
    # الإيميل واللينك والحساب مش لغة الطلب — العنوان مايغلبش الطلب العربي
    "اكتب رسالة إلى support@example.com", "ابعت اللينك ده https://api.example.com/app لأمي",
    "اكتب تهنئة لـ @mohamed_ahmed_official",
    # لاتيني أكتر من العربي بس فيه طلب عربي — مخلوط، مش «إنجليزي»
    "اكتب إعلان لدورة JavaScript و TypeScript",
]
ENGLISH = [
    "Need a React app for my store", "build a docker container for me",
    "write a short bio for my LinkedIn", "write a thank-you note to support@example.com",
]


class TestPromptLanguage(unittest.TestCase):
    def test_empty_is_ar(self):
        # مفيش حاجة تتحول لبرومبت — القرار الافتراضي عربي
        self.assertEqual(smart.prompt_language(""), "ar")
        self.assertEqual(smart.prompt_language("   "), "ar")

    def test_english_is_decided_locally(self):
        for text in ENGLISH:
            self.assertEqual(smart.prompt_language(text), "en", text)

    def test_arabic_or_mixed_always_goes_to_the_classifier(self):
        for text in ARABIC_OR_MIXED:
            self.assertIsNone(smart.prompt_language(text), text)


# ── tech_guess: التخمين الاحتياطي لما التصنيف يفشل ──────────────────────────────
class TestTechGuess(unittest.TestCase):
    def test_strong_words_guess_en(self):
        for text in ("ظبط الداتابيز دي", "الابليكيشن بتاعي بيقع", "عايز سيرفرات جاهزة", "وبرمجة",
                     "عايز مطور برمجيات", "عايز API للدفع", "اعمل database للعملاء"):
            self.assertEqual(smart.tech_guess(text), "en", text)

    def test_ambiguous_or_plain_words_guess_ar(self):
        for text in ("اكتب لي برنامج غذائي لزيادة الوزن", "اشرح تطبيق القانون", "موقع البيت فين",
                     "اكتب رسالة للعملاء فيها كود خصم", "اكتب script لإعلان عطر جديد",
                     "اكتب رسالة شكر لمديري"):
            self.assertEqual(smart.tech_guess(text), "ar", text)

    def test_words_must_stand_alone(self):
        # substring كان بيمسك «ويب» جوّه «ويبقى» — التخمين نفسه لازم يتجنبه
        for text in ("ويبقى الكلام ده بينا", "عايز اتعلم تطوير الذات", "الكوديه دي غريبه"):
            self.assertEqual(smart.tech_guess(text), "ar", text)

    def test_links_are_not_technical_terms(self):
        # «api»/«app» جوّه لينك مش مصطلح تقني في الطلب
        self.assertEqual(smart.tech_guess("ابعت اللينك ده https://api.example.com/app لأمي"), "ar")


class TestPromptLangClassifier(unittest.TestCase):
    """providers.Client._prompt_lang: العربي/المخلوط بالتصنيف، والفشل بالتخمين."""

    def _client(self, classify):
        cl = providers.Client("groq", "test-key")
        calls = []

        def fake_raw(system, text, temperature=0.0):
            calls.append(text)
            return classify() if callable(classify) else classify

        cl._chat_raw = fake_raw
        return cl, calls

    def test_english_skips_classifier(self):
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("build a docker container"), "en")
        self.assertEqual(calls, [])

    def test_technical_word_still_asks_the_classifier(self):
        # «اكتب إعلانًا لدورة Python» فيها مصطلح تقني بس طلب كتابة — التصنيف يقرر
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("اكتب إعلانًا لدورة Python"), "ar")
        self.assertEqual(len(calls), 1)

    def test_other_maps_ar_and_tech_maps_en(self):
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي لزيادة الوزن"), "ar")
        self.assertEqual(len(calls), 1)                # اتسأل مرة واحدة بس
        cl, _ = self._client("TECH")
        self.assertEqual(cl._prompt_lang("ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين"), "en")

    def test_failure_falls_back_to_the_keyword_guess(self):
        boom = lambda system, text, temperature=0.0: (_ for _ in ()).throw(RuntimeError("boom"))  # noqa: E731
        for answer in (boom, "MAYBE", None):
            cl, _ = self._client(answer if not callable(answer) else None)
            if callable(answer):
                cl._chat_raw = answer
            # من غير تصنيف: كلمة تقنية قوية = إنجليزي، وغير كده عربي
            self.assertEqual(cl._prompt_lang("ظبط الداتابيز دي"), "en", repr(answer))
            self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي"), "ar", repr(answer))


class TestToPromptDirective(unittest.TestCase):
    def _capture(self, text, classify):
        """fake _chat بيحجز الـsystem ويرجّع النص، وfake _chat_raw بيرجّع تصنيف ثابت."""
        cl = providers.Client("groq", "test-key")
        captured = []
        cl._chat = lambda system, text, temperature=0.2: captured.append(system) or text
        cl._chat_raw = lambda system, text, temperature=0.0: classify
        cl.to_prompt(text)
        return captured

    def test_ar_directive_for_writing_request(self):
        captured = self._capture("اكتب إعلانًا لدورة Python", "OTHER")
        self.assertEqual(len(captured), 1)
        self.assertIn(providers.PROMPT_OUTPUT_AR, captured[0])
        self.assertNotIn(providers.PROMPT_OUTPUT_EN, captured[0])

    def test_en_directive_for_software_request(self):
        captured = self._capture("ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين", "TECH")
        self.assertEqual(len(captured), 1)
        self.assertIn(providers.PROMPT_OUTPUT_EN, captured[0])
        self.assertNotIn(providers.PROMPT_OUTPUT_AR, captured[0])


class TestToPromptRetry(unittest.TestCase):
    def test_ar_english_result_retries_once(self):
        # القرار "ar" بس الموديل رد بإنجليزي (فيه عنوان إنجليزي) → إعادة واحدة
        # بـdirective أول سطر، والنتيجة النهائية هي ناتج الإعادة.
        cl = providers.Client("groq", "test-key")
        captured = []
        responses = iter([
            "# Role & Expertise\nSenior Engineer\n# Context & Objective\n...",
            "# الدور والخبرة\nمهندس كبير\n# السياق والهدف\n...",
        ])

        def fake_chat(system, text, temperature=0.2):
            captured.append(system)
            return next(responses)

        cl._chat = fake_chat
        with mock.patch.object(smart, "prompt_language", return_value="ar"):
            out = cl.to_prompt("اكتب رسالة شكر لمديري")
        self.assertEqual(len(captured), 2)
        self.assertEqual(out, "# الدور والخبرة\nمهندس كبير\n# السياق والهدف\n...")
        # الإعادة: الـdirective أول سطر في الـsystem prompt
        self.assertTrue(captured[1].startswith(providers.PROMPT_OUTPUT_AR))

    def test_failed_retry_keeps_the_first_prompt(self):
        # الإعادة فشلت (_chat رجّع الكلام الخام): البرومبت الأول (لغة غلط) أنفع من
        # الكلام الخام — ميتبدلش بيه، وسجل المحرك يفضل على النداء الأول اللي نجح
        cl = providers.Client("groq", "test-key")
        first = "# Role & Expertise\nSenior Engineer\n# Context & Objective\n..."
        dictated = "اكتب رسالة شكر لمديري"
        calls = []

        def fake_chat(system, text, temperature=0.2):
            calls.append(system)
            if len(calls) == 1:
                cl.last_chat = ("Groq", "m1")
                return first
            cl.last_chat = None
            return text                      # فشل الإعادة = الكلام الخام

        cl._chat = fake_chat
        with mock.patch.object(smart, "prompt_language", return_value="ar"):
            out = cl.to_prompt(dictated)
        self.assertEqual(len(calls), 2)
        self.assertEqual(out, first)
        self.assertEqual(cl.last_chat, ("Groq", "m1"))

    def test_en_never_retries(self):
        cl = providers.Client("groq", "test-key")
        captured = []
        cl._chat = lambda system, text, temperature=0.2: captured.append(system) or "an english prompt"
        with mock.patch.object(smart, "prompt_language", return_value="en"):
            out = cl.to_prompt("build a docker container")
        self.assertEqual(len(captured), 1)
        self.assertEqual(out, "an english prompt")


if __name__ == "__main__":
    unittest.main()
