"""
الوضع العادي بيتعرّف على لغة الكلام لوحده (عربي أو إنجليزي) بدل ما يجبر التفريغ على العربي:
Whisper لما بيتجبر على "ar" والكلام إنجليزي بيترجمه («How are you» ← «كيف تتعرّف؟»).
- smart.foreign_script: علامة إن التعرّف التلقائي غلط (فارسي/أوردو/…) → نعيد كعربي
- polish: النص الإنجليزي بيتنضّف بقواعد إنجليزي ومبيتعرّبش
- offline.transcribe(None): نفس حماية الحروف الأجنبية اللي في Client.transcribe
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart      # noqa: E402
import providers  # noqa: E402

from unit_offline import _BaseCase, offline  # noqa: E402


class TestForeignScript(unittest.TestCase):
    def test_persian_and_urdu_letters_are_foreign(self):
        self.assertTrue(smart.foreign_script("سلام چطوری"))
        self.assertTrue(smart.foreign_script("یہ ٹھیک ہے"))

    def test_arabic_english_and_empty_are_not_foreign(self):
        for text in ("عايز أرفع الـ API على Docker", "How are you doing today?", "", None):
            self.assertFalse(smart.foreign_script(text), text)


class TestFixMixedLeavesEnglishAlone(unittest.TestCase):
    def test_pure_english_is_unchanged(self):
        text = "How are you doing today? Let's ship it, then review."
        self.assertEqual(smart.fix_mixed(text), text)


class TestPolishLanguage(unittest.TestCase):
    def setUp(self):
        self.cl = providers.Client("groq", "test-key")
        self.seen = []

    def _polish(self, text, reply=None, profile=None):
        def fake_chat(system, user, temperature=0.2):
            self.seen.append(system)
            return reply if reply is not None else user
        with mock.patch.object(self.cl, "_chat", side_effect=fake_chat), \
                mock.patch("core.log_error"):
            return self.cl.polish(text, profile=profile)

    def test_english_text_uses_english_prompt(self):
        self._polish("how are you doing today")
        self.assertEqual(self.seen, [providers.POLISH_SYSTEM_EN])

    def test_arabic_and_mixed_text_keep_arabic_prompt(self):
        self._polish("عايز أرفع الـ API على Docker")
        self._polish("Let's push the code بكرة")
        self.assertEqual(self.seen, [providers.POLISH_SYSTEM, providers.POLISH_SYSTEM])

    def test_english_prompt_skips_arabic_style_rules(self):
        self._polish("run the build again", profile="dev")
        self.assertEqual(self.seen, [providers.POLISH_SYSTEM_EN])

    def test_arabic_reply_to_english_text_returns_raw(self):
        # الموديل ترجم بدل ما ينضّف — الخام الإنجليزي أأمن من نص عربي ماتقالش
        out = self._polish("how are you", reply="كيف حالك؟")
        self.assertEqual(out, "how are you")
        self.assertIsNone(self.cl.last_chat)

    def test_english_reply_to_english_text_is_kept(self):
        out = self._polish("how are you", reply="How are you?")
        self.assertEqual(out, "How are you?")

    def test_identifier_only_correction_is_kept(self):
        # PR #13 (Codex P2): is_english بيشيل الإيميل/اللينك قبل العدّ — رد كله معرّفات
        # مش «عربي»، فالتصحيح لازم يعدّي
        for raw, fixed in (("john at example dot com", "john@example.com"),
                           ("example dot com slash docs", "https://example.com/docs")):
            self.assertEqual(self._polish(raw, reply=fixed), fixed)


class TestOfflineAutoLanguage(_BaseCase):
    def _fake_run(self, outputs):
        langs = []

        def _run(cmd, timeout=None):
            langs.append(cmd[cmd.index("-l") + 1])
            out_base = cmd[cmd.index("-of") + 1]
            with open(out_base + ".txt", "w", encoding="utf-8") as f:
                f.write(outputs[len(langs) - 1])
            return mock.Mock(returncode=0)

        return _run, langs

    def test_foreign_script_on_auto_retries_as_arabic(self):
        self._install("base")
        fake_run, langs = self._fake_run(["سلام چطوری", "سلام عامل ايه"])
        with mock.patch.object(offline, "_run", fake_run):
            text = offline.transcribe("w.wav", None)
        self.assertEqual(langs, ["auto", "ar"])
        self.assertEqual(text, "سلام عامل ايه")

    def test_english_on_auto_runs_once(self):
        self._install("base")
        fake_run, langs = self._fake_run(["How are you doing today?"])
        with mock.patch.object(offline, "_run", fake_run):
            text = offline.transcribe("w.wav", None)
        self.assertEqual(langs, ["auto"])
        self.assertEqual(text, "How are you doing today?")

    def test_forced_arabic_never_retries(self):
        self._install("base")
        fake_run, langs = self._fake_run(["سلام چطوری"])
        with mock.patch.object(offline, "_run", fake_run):
            offline.transcribe("w.wav", "ar")
        self.assertEqual(langs, ["ar"])


if __name__ == "__main__":
    unittest.main()
