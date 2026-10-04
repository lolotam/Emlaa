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


if __name__ == "__main__":
    unittest.main()
