# -*- coding: utf-8 -*-
"""اختبارات source/smart.py — دوال نقية، فمن غير شبكة ولا مفاتيح ولا ميكروفون."""
import os
import sys
import unittest

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart  # noqa: E402


class TestContract(unittest.TestCase):
    def test_all_contract_names_exist(self):
        for name in ("normalize", "word_count", "should_bypass", "light_clean", "fix_mixed",
                     "app_profile", "insert_target", "match_snippet", "is_network_error"):
            self.assertTrue(callable(getattr(smart, name, None)), name)

    def test_smart_does_not_import_core(self):
        # الاتجاه واحد: core بيستورد smart، والعكس يعمل دورة استيراد
        src = open(smart.__file__, encoding="utf-8").read()
        self.assertNotIn("import core", src)


class TestNormalize(unittest.TestCase):
    def test_plan_example(self):
        self.assertEqual(smart.normalize("إيميلي الشخصي!"), "ايميلي الشخصي")

    def test_tashkeel_stripped(self):
        self.assertEqual(smart.normalize("مُصْطَفَى"), "مصطفي")
        self.assertEqual(smart.normalize("سَلامٌ يا صَدِيقِي"), "سلام يا صديقي")

    def test_hamza_forms_unified(self):
        self.assertEqual(smart.normalize("أحمد وإسماعيل وآمنة"), "احمد واسماعيل وامنه")

    def test_alef_maqsura_and_ta_marbuta(self):
        self.assertEqual(smart.normalize("مستشفى المدينة"), "مستشفي المدينه")

    def test_tatweel_removed(self):
        self.assertEqual(smart.normalize("للـbranch"), "للbranch")
        self.assertEqual(smart.normalize("الـ API"), smart.normalize("ال API"))

    def test_latin_lowercased(self):
        self.assertEqual(smart.normalize("PUSH the Branch"), "push the branch")

    def test_arabic_and_ascii_punctuation_removed(self):
        self.assertEqual(smart.normalize("تمام، شكراً.؟! (نعم)"), "تمام شكرا نعم")

    def test_spaces_collapsed(self):
        self.assertEqual(smart.normalize("  تمام\tشكرا\nيا   صديقي "), "تمام شكرا يا صديقي")

    def test_digits_kept(self):
        self.assertEqual(smart.normalize("غرفة 12، ٣ أيام"), "غرفه 12 ٣ ايام")

    def test_decomposed_input_matches_composed(self):
        import unicodedata
        word = "آمنة"
        self.assertEqual(smart.normalize(unicodedata.normalize("NFD", word)), smart.normalize(word))

    def test_empty_and_blank(self):
        self.assertEqual(smart.normalize(""), "")
        self.assertEqual(smart.normalize(None), "")
        self.assertEqual(smart.normalize("   \n  "), "")

    def test_idempotent(self):
        for s in ("إيميلي الشخصي!", "مُصْطَفَى", "PUSH the Branch", "للـbranch ده، وافتح PR?",
                  "تمام، شكراً.؟! (نعم)", ""):
            once = smart.normalize(s)
            self.assertEqual(smart.normalize(once), once, s)


class TestWordCount(unittest.TestCase):
    def test_plan_example(self):
        self.assertEqual(smart.word_count("تمام، شكراً."), 2)

    def test_mixed_arabic_english(self):
        self.assertEqual(smart.word_count("اعمل push للـ branch ده، وافتح PR?"), 7)

    def test_punctuation_only(self):
        self.assertEqual(smart.word_count("،،، !!!"), 0)
        self.assertEqual(smart.word_count(""), 0)


def _cfg(**over):
    """إعدادات عليها قيم F2 الافتراضية — كل اختبار بيغيّر مفتاح واحد."""
    base = {"polish": True, "bypass_short": True, "bypass_max_words": 3, "dictionary": []}
    base.update(over)
    return base


class TestShouldBypass(unittest.TestCase):
    def test_short_arabic_reply(self):
        self.assertTrue(smart.should_bypass("تمام شكرا", "normal", _cfg()))

    def test_short_english_reply(self):
        self.assertTrue(smart.should_bypass("Yes please", "normal", _cfg()))

    def test_punctuation_and_spelling_variants_ignored(self):
        # التطبيع مش العرض: «شكرًا» و«شكرا» و«إيوه» كلها تاخد نفس القرار
        self.assertTrue(smart.should_bypass("تمام!", "normal", _cfg()))
        self.assertTrue(smart.should_bypass("إيوه، شكرًا", "normal", _cfg()))

    def test_latin_and_digit_tokens_allowed(self):
        self.assertTrue(smart.should_bypass("تمام ok 123", "normal", _cfg()))

    def test_four_words_over_default_limit(self):
        # كل الكلمات من القايمة بس العدد فوق الحد التلات
        self.assertFalse(smart.should_bypass("شكرا يا حبيبي ربنا", "normal", _cfg()))
        self.assertFalse(smart.should_bypass("yes please sure thanks", "normal", _cfg()))

    def test_max_words_from_config(self):
        self.assertTrue(smart.should_bypass("شكرا يا حبيبي ربنا", "normal",
                                            _cfg(bypass_max_words=4)))

    def test_prompt_mode_never_bypasses(self):
        self.assertFalse(smart.should_bypass("تمام", "prompt", _cfg()))

    def test_translate_mode_never_bypasses(self):
        self.assertFalse(smart.should_bypass("تمام", "translate", _cfg()))

    def test_raw_mode_never_bypasses(self):
        # الوضع الخام: النص بيرجع زي ما اتفرّغ — مفيش تخطّي ولا تعديل
        self.assertFalse(smart.should_bypass("تمام", "normal", _cfg(polish=False)))

    def test_disabled_by_config(self):
        self.assertFalse(smart.should_bypass("تمام", "normal", _cfg(bypass_short=False)))

    def test_empty_text(self):
        self.assertFalse(smart.should_bypass("", "normal", _cfg()))

    def test_transliterated_word_not_bypassed(self):
        # نقل عربي لنطق منتج — مش من القايمة، حتى والقاموس فاضي (R1 #15)
        self.assertFalse(smart.should_bypass("دوكر", "normal", _cfg(dictionary=[])))

    def test_product_name_not_bypassed(self):
        self.assertFalse(smart.should_bypass("سوبابيز تمام", "normal", _cfg()))

    def test_person_name_not_bypassed(self):
        self.assertFalse(smart.should_bypass("أحمد", "normal", _cfg()))

    def test_list_entries_are_normalized(self):
        # عنصر مكتوب بشكل غير مطبّع (أ أو ة) عمره ما هيطابق — القايمة لازم تتكتب مطبّعة
        self.assertEqual([w for w in smart.SHORT_REPLIES if smart.normalize(w) != w], [])

    def test_common_egyptian_replies(self):
        for reply in ("آسف", "متشكر جدا".split()[0], "حلو أوي".split()[0], "مع السلامة"):
            self.assertTrue(smart.should_bypass(reply, "normal", _cfg()), reply)


class TestLightClean(unittest.TestCase):
    def test_strips_and_collapses_spaces(self):
        self.assertEqual(smart.light_clean("  تمام   يا  رب "), "تمام يا رب")

    def test_removes_one_trailing_period(self):
        # Whisper بيزود نقطة ورا الكلمة الواحدة — دي اللي بنشيلها
        self.assertEqual(smart.light_clean("تمام."), "تمام")
        self.assertEqual(smart.light_clean("Yes please."), "Yes please")

    def test_removes_cjk_period(self):
        self.assertEqual(smart.light_clean("تمام。"), "تمام")

    def test_keeps_period_when_more_than_three_words(self):
        s = "تمام شكرا يا رب."
        self.assertEqual(smart.light_clean(s), s)

    def test_removes_only_one_period(self):
        self.assertEqual(smart.light_clean("تمام.."), "تمام.")

    def test_empty_and_none(self):
        self.assertEqual(smart.light_clean(""), "")
        self.assertEqual(smart.light_clean(None), "")


if __name__ == "__main__":
    unittest.main()
