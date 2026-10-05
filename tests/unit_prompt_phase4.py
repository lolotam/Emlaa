# -*- coding: utf-8 -*-
"""
اختبارات Task 18 — تنضيف البرومبت (PROMPT_SYSTEM من غير أسماء موديلات).
البرومبت المركّب لازم يحتوي على العناوين الإنجليزي الخمسة والعناوين العربي الخمسة
وقاعدة اللغة، ومن غير أي اسم موديل محدد.
"""
import os
import sys
import unittest

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import providers  # noqa: E402

EN_HEADERS = [
    "# Role & Expertise",
    "# Context & Objective",
    "# Detailed Requirements",
    "# Constraints & Guidelines",
    "# Expected Output",
]

AR_HEADERS = [
    "# الدور والخبرة",
    "# السياق والهدف",
    "# المتطلبات التفصيلية",
    "# القيود والإرشادات",
    "# المخرج المتوقع",
]

MODEL_NAMES = (
    "Claude 3.7", "GPT-4o", "GPT-4", "gpt-4o", "gpt-4", "gpt-4o-mini",
    "Claude", "ChatGPT", "Gemini 3", "gemini-3", "whisper-large", "whisper-1",
)


class TestPromptCleanup(unittest.TestCase):
    def _compose(self):
        # نفس التركيبة اللي Client.to_prompt بيستخدمها
        return providers.PROMPT_SYSTEM + "\n\n" + providers.PROMPT_GUARDRAILS + "\n" + providers.STT_FIX_RULE

    def test_contains_five_english_headers(self):
        text = self._compose()
        for h in EN_HEADERS:
            self.assertIn(h, text)

    def test_contains_five_arabic_headers(self):
        text = self._compose()
        for h in AR_HEADERS:
            self.assertIn(h, text)

    def test_contains_language_rule(self):
        text = self._compose()
        self.assertIn("Language Handling", text)
        self.assertIn("The output language follows the TOPIC", text)

    def test_no_model_names(self):
        text = self._compose()
        for name in MODEL_NAMES:
            self.assertNotIn(name, text)


if __name__ == "__main__":
    unittest.main()
