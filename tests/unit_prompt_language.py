# -*- coding: utf-8 -*-
"""
اختبارات F2 — لغة البرومبت: قرار مبدئي في الكود (smart.prompt_language) والقرار
النهائي في providers._prompt_lang (تصنيف TECH/OTHER للموديل لما القرار المبدئي None)،
والـdirective بيتضاف للنظام، والإعادة بتحصل مرة واحدة بس لو الموديل رد باللغة الغلط.
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


# ── prompt_language: جدول حالات (قوي=en / ملتبس أو عادي=None) ───────────────────
# القرار هنا مبدئي: "en" للتقني الأكيد بس، وNone لكل حاجة تانية (ومنها العربي العادي
# من غير كلمة تقنية) — لأن «ابني متجر إلكتروني فيه سلة مشتريات» تقني من غير أي كلمة
# قوية، فالكود مينفعش يقررها لوحده. العربي العادي بيرجّع None مش "ar" عشان القرار
# النهائي ييجي من تصنيف الموديل (OTHER → "ar").
CASES = [
    # كلمات تقنية قوية = "en" أكيد
    ("ظبط الكود ده", "en"),                       # كود
    ("عايز ابليكيشن للسوبر ماركت", "en"),          # ابليكيشن (مصري)
    ("اعمل الويب سايت بتاعي", "en"),               # الويب سايت
    ("عايز اتعلم برمجة", "en"),                   # برمجة
    ("عايز قاعدة بيانات للعملاء", "en"),          # قاعدة بيانات
    ("عايز اعمل سيرفر للشركة", "en"),             # سيرفر
    ("عايز مطور فرونت اند", "en"),                # فرونت اند
    ("عايز مطور برمجيات", "en"),                  # مطور برمجيات (مركّبة)
    ("الصفحة دي فيها داشبورد", "en"),             # داشبورد
    # لاتيني تقني أو لاتيني-الغالب = "en"
    ("Need a React app for my store", "en"),
    ("build a docker container for me", "en"),
    # كلمات ملتبسة بس = None (القرار بتاعها للموديل)
    ("اكتب لي برنامج غذائي لزيادة الوزن", None),  # برنامج = غذائي مش تقني
    ("اشرح تطبيق القانون", None),                 # تطبيق = القانون
    ("عايز برنامج تمارين", None),                  # برنامج
    ("موقع البيت فين", None),                      # موقع = مكان
    ("ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين", None),  # تقني بس من غير كلمة قوية
    ("عايز صفحة تسجيل دخول بالإيميل والباسورد", None),         # تسجيل دخول ملتبسة
    # عربي عادي من غير كلمة تقنية = None (التصنيف بيأكد OTHER)
    ("اكتب رسالة شكر لمديري", None),
    ("ساعدني أكتب جواب لصاحبي", None),
    ("اكتب بوست عن الطبخ", None),
    ("اكتبلي ايميل رسمي للمدير", None),
    ("اكتب رسالة اعتذار لزميلي", None),
]


class TestPromptLanguage(unittest.TestCase):
    def test_empty_is_ar(self):
        # مفيش حاجة تتحول لبرومبت — القرار الافتراضي عربي
        self.assertEqual(smart.prompt_language(""), "ar")
        self.assertEqual(smart.prompt_language("   "), "ar")

    def test_tech_words_must_stand_alone(self):
        # كلمة تقنية مش موجودة كاملة (substring/لاحقة غلط) = مش "en" — قبل كده
        # «ويب» جوه «ويبقى» و«كود» جوه «الكوديه» كانت بتطلع برومبت إنجليزي غلط
        for text in ("ويبقى الكلام ده بينا", "عايز اتعلم تطوير الذات", "الكوديه دي غريبه"):
            self.assertEqual(smart.prompt_language(text), None, text)
        # الكلمة القوية نفسها بسابقة/لاحقة عادية لسه بتتمسك
        for text in ("الابليكيشن بتاعي بيقع", "عايز أكواد جاهزة", "وبرمجة"):
            self.assertEqual(smart.prompt_language(text), "en", text)

    def test_table(self):
        for text, expected in CASES:
            self.assertEqual(smart.prompt_language(text), expected, text)


class TestPromptLangClassifier(unittest.TestCase):
    """providers.Client._prompt_lang: القرار النهائي بالتصنيف لما القرار المبدئي None."""

    def _client(self, classify):
        cl = providers.Client("groq", "test-key")
        calls = []

        def fake_raw(system, text, temperature=0.0):
            calls.append(text)
            return classify() if callable(classify) else classify

        cl._chat_raw = fake_raw
        return cl, calls

    def test_strong_case_skips_classifier(self):
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("ظبط الكود ده"), "en")
        self.assertEqual(calls, [])                    # كلمة قوية = مفيش نداء تصنيف

    def test_latin_dominant_skips_classifier(self):
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("build a docker container"), "en")
        self.assertEqual(calls, [])

    def test_ambiguous_other_maps_ar(self):
        cl, calls = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي لزيادة الوزن"), "ar")
        self.assertEqual(len(calls), 1)                # اتسأل مرة واحدة بس

    def test_ambiguous_tech_maps_en(self):
        cl, _ = self._client("TECH")
        self.assertEqual(cl._prompt_lang("ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين"), "en")

    def test_plain_arabic_other_maps_ar(self):
        cl, _ = self._client("OTHER")
        self.assertEqual(cl._prompt_lang("اكتب رسالة شكر لمديري"), "ar")

    def test_exception_falls_back_ar(self):
        cl, _ = self._client("OTHER")
        cl._chat_raw = lambda system, text, temperature=0.0: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي"), "ar")

    def test_unexpected_answer_falls_back_ar(self):
        cl, _ = self._client("MAYBE")
        self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي"), "ar")

    def test_none_answer_falls_back_ar(self):
        cl, _ = self._client(None)
        self.assertEqual(cl._prompt_lang("اكتب لي برنامج غذائي"), "ar")


class TestToPromptDirective(unittest.TestCase):
    def _capture(self, text, classify):
        """fake _chat بيحجز الـsystem ويرجّع النص، وfake _chat_raw بيرجّع تصنيف ثابت."""
        cl = providers.Client("groq", "test-key")
        captured = []
        cl._chat = lambda system, text, temperature=0.2: captured.append(system) or text
        cl._chat_raw = lambda system, text, temperature=0.0: classify
        cl.to_prompt(text)
        return captured

    def test_ar_directive_for_ambiguous_other(self):
        captured = self._capture("اكتب لي برنامج غذائي لزيادة الوزن", "OTHER")
        self.assertEqual(len(captured), 1)
        self.assertIn(providers.PROMPT_OUTPUT_AR, captured[0])
        self.assertNotIn(providers.PROMPT_OUTPUT_EN, captured[0])

    def test_en_directive_for_ambiguous_tech(self):
        captured = self._capture("ابني متجر إلكتروني فيه سلة مشتريات ودفع أونلاين", "TECH")
        self.assertEqual(len(captured), 1)
        self.assertIn(providers.PROMPT_OUTPUT_EN, captured[0])
        self.assertNotIn(providers.PROMPT_OUTPUT_AR, captured[0])

    def test_strong_case_skips_classifier(self):
        # كلمة قوية (كود) = القرار "en" من غير نداء تصنيف، والـdirective إنجليزي
        cl = providers.Client("groq", "test-key")
        captured = []
        classified = []
        cl._chat = lambda system, text, temperature=0.2: captured.append(system) or text
        cl._chat_raw = lambda system, text, temperature=0.0: classified.append(text) or "OTHER"
        cl.to_prompt("ظبط الكود ده")
        self.assertEqual(len(captured), 1)
        self.assertEqual(classified, [])
        self.assertIn(providers.PROMPT_OUTPUT_EN, captured[0])


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
