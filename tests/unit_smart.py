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
        with open(smart.__file__, encoding="utf-8") as f:
            src = f.read()
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


class TestAppProfile(unittest.TestCase):
    def test_builtin_map_from_plan(self):
        # حالات الخطة بالظبط — من غير أي override الأسلوب لازم يشتغل من أول تشغيل
        self.assertEqual(smart.app_profile("Code", _cfg()), "dev")
        self.assertEqual(smart.app_profile("WhatsApp", _cfg()), "chat")
        self.assertEqual(smart.app_profile("OUTLOOK", _cfg()), "formal")
        self.assertIsNone(smart.app_profile("chrome", _cfg()))

    def test_override_beats_builtin(self):
        self.assertEqual(smart.app_profile("chrome", _cfg(app_profiles={"chrome": "formal"})), "formal")
        self.assertEqual(smart.app_profile("code", _cfg(app_profiles={"code": "chat"})), "chat")

    def test_context_styles_off_disables_builtin_too(self):
        self.assertIsNone(smart.app_profile("code", _cfg(context_styles=False)))

    def test_builtin_values_are_valid_profiles(self):
        self.assertTrue(set(smart.BUILTIN_PROFILES.values()) <= set(smart.PROFILES))
        self.assertTrue(all(k == k.lower() and not k.endswith(".exe") for k in smart.BUILTIN_PROFILES))

    def test_matching_profile_case_insensitive(self):
        cfg = _cfg(app_profiles={"vscode": "dev"})
        self.assertEqual(smart.app_profile("VSCode", cfg), "dev")
        self.assertEqual(smart.app_profile("  VSCODE  ", cfg), "dev")
        self.assertEqual(smart.app_profile("EXCEL", _cfg(app_profiles={"excel": "formal"})), "formal")

    def test_no_override_for_other_apps(self):
        cfg = _cfg(app_profiles={"vscode": "dev"})
        self.assertIsNone(smart.app_profile("chrome", cfg))
        self.assertIsNone(smart.app_profile("notepad", _cfg(app_profiles={})))

    def test_empty_exe_is_none(self):
        cfg = _cfg(app_profiles={"vscode": "dev"})
        for exe in ("", None, "   ", "\t"):
            self.assertIsNone(smart.app_profile(exe, cfg), repr(exe))

    def test_disabled_by_context_styles(self):
        cfg = _cfg(context_styles=False, app_profiles={"vscode": "dev"})
        self.assertIsNone(smart.app_profile("vscode", cfg))

    def test_missing_context_styles_key_defaults_on(self):
        # إعدادات قديمة من قبل F5 مابهاش مفتاح context_styles — السلكت الافتراضي شغّال
        self.assertEqual(smart.app_profile("excel", _cfg(app_profiles={"excel": "formal"})), "formal")

    def test_invalid_stored_value_is_none(self):
        # قيمة محفوظة غلط (نسخة قديمة أو تعديل يدوي) متبعتش للـmodel
        for bad in ("poetic", "", None, "DEV"):
            self.assertIsNone(smart.app_profile("vscode", _cfg(app_profiles={"vscode": bad})), repr(bad))

    def test_non_dict_app_profiles_is_none(self):
        self.assertIsNone(smart.app_profile("vscode", _cfg(app_profiles=["dev"])))
        self.assertIsNone(smart.app_profile("vscode", _cfg(app_profiles=None)))

    def test_only_valid_keys_exist(self):
        self.assertEqual(smart.PROFILES, ("dev", "chat", "formal"))


class TestInsertTarget(unittest.TestCase):
    """F3: تصنيف الهدف واستراتيجية الحقن — قرار نقي من معلومات UIA واسم الـexe."""

    def info(self, **over):
        """معلومات هدف عادية (حد قابل للكتابة) — كل اختبار بيمسح مفتاح أو اتنين."""
        base = {"is_password": False, "class": "", "exe": "", "editable": True}
        base.update(over)
        return base

    def test_table_from_plan(self):
        cases = [
            # (info, text, method, الناتج المتوقع (نوع، استراتيجية، نص))
            (self.info(is_password=True), "s3cret!", "auto",
             ("secure", "type", "s3cret!")),
            (self.info(is_password=True), "a\nb", "type",
             ("secure", "type", "a b")),
            (self.info(exe="MSTSC"), "hi", "auto",
             ("remote", "type", "hi")),
            (self.info(exe="mstsc"), "a\nb", "auto",
             ("remote", "ctrl_v", "a\nb")),
            (self.info(**{"class": "TermControl"}), "ls -la", "auto",
             ("terminal", "shift_insert", "ls -la")),
            (self.info(**{"class": "TermControl"}), "a\nb", "auto",
             ("terminal", "handoff", "a\nb")),
            (self.info(), "abcdefghij", "auto",
             ("gui", "type", "abcdefghij")),
            (self.info(), "a" * 41, "auto",
             ("gui", "ctrl_v", "a" * 41)),
            (self.info(), "a\nb", "auto",
             ("gui", "ctrl_v", "a\nb")),
            (self.info(), "hi", "type",
             ("gui", "type", "hi")),
        ]
        for info, text, method, expected in cases:
            self.assertEqual(smart.insert_target(info, text, method), expected,
                             f"{info} | {text!r} | {method}")

    def test_secure_newlines_become_spaces_even_with_crlf(self):
        self.assertEqual(smart.insert_target(self.info(is_password=True), "a\r\nb\nc", "auto"),
                         ("secure", "type", "a b c"))

    def test_uia_failure_is_gui_not_secure(self):
        # R1 #1: فشل UIA (None) = سلوك اليوم «gui» — عتباره secure كان هيخفّ السجل
        info = self.info(is_password=None, editable=None)
        self.assertEqual(smart.insert_target(info, "مرحبا", "auto"),
                         ("gui", "type", "مرحبا"))

    def test_no_text_field_is_handoff(self):
        # UIA قال صريح إن مفيش خانة كتابة: نسخ + عرض بالواجهة، ممن يتحقن
        self.assertEqual(smart.insert_target(self.info(editable=False), "مرحبا", "auto"),
                         ("gui", "handoff", "مرحبا"))

    def test_remote_exe_beats_no_text_field(self):
        # UIA مبيشوفش جوّه جلسة RDP — بيشوف نافذة mstsc نفسها فبيقول editable=False،
        # والكيبورد في الحقيقة رايح للجلسة. لو «مفيش خانة» كسب، عمرنا ما هنكتب في RDP.
        self.assertEqual(smart.insert_target(self.info(editable=False, exe="mstsc"), "مرحبا", "auto"),
                         ("remote", "type", "مرحبا"))

    def test_terminal_by_exe(self):
        self.assertEqual(smart.insert_target(self.info(exe="WindowsTerminal"), "echo hi", "auto"),
                         ("terminal", "shift_insert", "echo hi"))
        self.assertEqual(smart.insert_target(self.info(exe="conemu64"), "a\nb", "auto"),
                         ("terminal", "handoff", "a\nb"))

    def test_secure_beats_remote_exe(self):
        # الباسورد جاي الأول دايما — حتى لو exe الجلسة البعيدة
        self.assertEqual(smart.insert_target(self.info(is_password=True, exe="mstsc"), "x", "auto"),
                         ("secure", "type", "x"))

    def test_remote_exe_case_insensitive_and_stripped(self):
        self.assertEqual(smart.insert_target(self.info(exe="  MSTSC "), "hi", "auto"),
                         ("remote", "type", "hi"))

    def test_gui_paste_method_always_ctrl_v(self):
        self.assertEqual(smart.insert_target(self.info(), "مرحبا", "paste"),
                         ("gui", "ctrl_v", "مرحبا"))
        self.assertEqual(smart.insert_target(self.info(), "a\nb", "paste"),
                         ("gui", "ctrl_v", "a\nb"))

    def test_gui_type_method_keeps_legacy_multiline_paste(self):
        # «type» القديمي: المتعدد لازم يتلزق مرة واحدة (Enter حرف حرف = إرسال مبكر)
        self.assertEqual(smart.insert_target(self.info(), "a\nb", "type"),
                         ("gui", "ctrl_v", "a\nb"))

    def test_gui_auto_boundary_40_chars(self):
        # > 40 = Ctrl+V، و40 بالظبط لسه حرف حرف
        self.assertEqual(smart.insert_target(self.info(), "a" * 40, "auto")[1], "type")
        self.assertEqual(smart.insert_target(self.info(), "a" * 41, "auto")[1], "ctrl_v")

    def test_unknown_method_falls_back_to_legacy(self):
        # قيمة محفوظة غلط = سلوك قديم (حرف حرف غير المتعدد) مش كارثة
        self.assertEqual(smart.insert_target(self.info(), "مرحبا", "قلم"),
                         ("gui", "type", "مرحبا"))

    def test_none_inputs_do_not_raise(self):
        self.assertEqual(smart.insert_target(None, None, None),
                         ("gui", "type", ""))


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

