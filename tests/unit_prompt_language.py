# -*- coding: utf-8 -*-
"""
اختبارات F2 — لغة البرومبت تتقرر في الكود (smart.prompt_language) مش في الموديل،
والـdirective بيتضاف للنظام، والإعادة بتحصل مرة واحدة بس لو الموديل رد باللغة الغلط.
مفيش شبكة ولا مفاتيح: _chat متزوّد fake بيحجز الـsystem prompt، والمخرجات ثابتة.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart      # noqa: E402
import providers  # noqa: E402


# ── prompt_language: جدول حالات (عربي/إنجليزي/مختلط) ───────────────────────────
# كل (نص، لغة متوقّعة) — بيغطّي الكتابات المصرية للكلمات التقنية والطلبات غير التقنية.
CASES = [
    ("اكتب رسالة شكر لمديري", "ar"),              # طلب غير تقني
    ("اعمل تطبيق للموظفين", "en"),                # تطبيق
    ("عايز ابليكيشن للسوبر ماركت", "en"),          # ابليكيشن (مصري)
    ("اعمل الويب سايت بتاعي", "en"),               # الويب سايت
    ("ظبط الكود ده", "en"),                       # كود
    ("ساعدني أكتب جواب لصاحبي", "ar"),            # غير تقني
    ("عايز اتعلم برمجة", "en"),                   # برمجة
    ("Need a React app for my store", "en"),      # لاتيني تقني
    ("build a docker container for me", "en"),    # لاتيني تقني
    ("عايز قاعدة بيانات للعملاء", "en"),          # قاعدة بيانات
    ("اكتب بوست عن الطبخ", "ar"),                 # غير تقني
    ("عايز اعمل سيرفر للشركة", "en"),             # سيرفر
    ("اكتبلي ايميل رسمي للمدير", "ar"),           # غير تقني
    ("عايز مطور فرونت اند", "en"),                # فرونت اند + مطور
    ("اكتب رسالة اعتذار لزميلي", "ar"),           # غير تقني
]


class TestPromptLanguage(unittest.TestCase):
    def test_tech_words_must_stand_alone(self):
        # substring كان بيمسك «ويب» جوّه «ويبقى» — طلب عربي عادي كان بيطلع برومبت إنجليزي
        for text in ("ويبقى الكلام ده بينا", "عايز اتعلم تطوير الذات", "الكوديه دي غريبه"):
            self.assertEqual(smart.prompt_language(text), "ar", text)
        # والكلمة نفسها بسابقة/لاحقة عادية لسه بتتمسك
        for text in ("وبالويب سايت", "عايز تطبيقات للموبايل", "الابليكيشن بتاعي بيقع"):
            self.assertEqual(smart.prompt_language(text), "en", text)

    def test_table(self):
        for text, expected in CASES:
            self.assertEqual(smart.prompt_language(text), expected, text)


class TestToPromptDirective(unittest.TestCase):
    def _capture(self, text):
        """بيدّي fake _chat بيحجز الـsystem ويرجّع النص نفسه (echo)."""
        cl = providers.Client("groq", "test-key")
        captured = []
        cl._chat = lambda system, text, temperature=0.2: captured.append(system) or text
        cl.to_prompt(text)
        return captured

    def test_ar_directive_appended_for_non_technical(self):
        captured = self._capture("اكتب رسالة شكر لمديري")
        self.assertEqual(len(captured), 1)
        self.assertIn(providers.PROMPT_OUTPUT_AR, captured[0])
        self.assertNotIn(providers.PROMPT_OUTPUT_EN, captured[0])

    def test_en_directive_appended_for_technical(self):
        captured = self._capture("build a docker container")
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
