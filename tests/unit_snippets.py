# -*- coding: utf-8 -*-
"""
اختبارات الاختصارات الصوتية (F8) — من غير شبكة ولا مفاتيح ولا ميكروفون:
توسيع الاختصار في دورة process، حماية خانة الباسورد، مفاتيح الاختصار في
الـSTT prompt، وعلّم نسخة الحافظة إنها بتاعتنا عشان المراقب مايسجلهاش.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import providers  # noqa: E402


GUI_FOCUS = {"is_password": False, "class": "Edit", "editable": True}



# التسجيل الفاشل بيتحفظ في السجل والتسجيلات — أي اختبار بيشغّل process لازم يكتب في
# مجلد مؤقت، عمره ما يلمس history.json أو recordings/ بتوع المستخدم
_store_patches = []


def setUpModule():
    import tempfile as _tempfile
    tmp = _tempfile.mkdtemp(prefix="emlaa_store_")
    for p in (mock.patch.object(core, "HISTORY_PATH", os.path.join(tmp, "history.json")),
              mock.patch.object(core, "RECORDINGS_DIR", os.path.join(tmp, "recordings"))):
        p.start()
        _store_patches.append(p)


def tearDownModule():
    while _store_patches:
        _store_patches.pop().stop()

class StubRec:
    """ميكروفون وهمي — دورة process مش بتلمسه، بس App لازم يلاقي واحد."""
    def ensure_open(self): return True
    def start(self): pass
    def stop(self): return "WAV"
    def discard(self): pass
    def close(self): pass


class FakeClient:
    """مزوّد وهمي: بيرجّع نص ثابت وبيحتفظ بسجل النداءات والمفاتيح الإضافية."""

    # زي chains.FeatureClient: مين فرّغ (محلي؟) وهل المعالجة ردّت
    stt_local = False
    ai_ok = True

    def __init__(self, text="مرحبا بالعالم"):
        self.vocab = []
        self.vocab_extra = []
        self.text = text
        self.calls = []
        self.last_chat = None

    def engine(self):
        return {"stt": "fake", "stt_model": "m1"}

    def transcribe(self, wav, lang):
        self.calls.append(("transcribe", lang))
        self.last_chat = None
        return self.text

    def polish(self, t, profile=None):
        self.calls.append(("polish", profile))
        self.last_chat = ("fake", "m1")
        return "p:" + t

    def to_prompt(self, t):
        self.calls.append(("prompt",))
        self.last_chat = ("fake", "m1")
        return "P:" + t

    def translate(self, t):
        self.calls.append(("translate",))
        self.last_chat = ("fake", "m1")
        return "T:" + t


def make_app(rec=None):
    """App من غير __init__ عشان مافتحناش ميكروفون حقيقي."""
    app = core.App.__new__(core.App)
    app.rec = rec or StubRec()
    app.recording = False
    app.busy = False
    app._op = None
    app._active_key = None
    app._client = None
    app._client_sig = None
    app._listener = None
    app.events = []
    app.on_state = lambda st, msg=None: app.events.append((st, msg))
    app.texts = []
    app.on_text = app.texts.append
    app.unplaced = []
    app.on_unplaced = app.unplaced.append
    return app


def _snippets_cfg():
    cfg = dict(core.DEFAULTS)
    cfg["snippets"] = [{"trigger": "إيميلي الشخصي", "text": "waleed@example.com"}]
    return cfg


class TestSnippetExpansion(unittest.TestCase):
    """F8: الكلام اللي كله اختصار محفوظ بيتوسّع لنص جاهز من غير أي لفة موديل."""

    def test_expands_in_normal_mode(self):
        app = make_app()
        fake = FakeClient(text="إيميلي الشخصي")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _snippets_cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None)], "مفيش polish للاختصار")
        paste.assert_called_once_with("waleed@example.com",
                                      ("gui", "type", "waleed@example.com"))
        self.assertEqual(hist.call_args[0][2], "[اختصار] إيميلي الشخصي",
                         "السجل بيحفظ المفتاح مش نص الاختصار الكامل")
        self.assertEqual(app.texts, ["waleed@example.com"])
        self.assertFalse(app.busy)

    def test_snippet_skips_fix_mixed(self):
        # نص الاختصار فيه «الAPI» — ممن يتعدّل (fix_mixed كان هيحوّلها لـ«الـ API»)
        app = make_app()
        fake = FakeClient(text="حساب البنك")
        app.client = lambda *a, **k: fake
        app.busy = True
        cfg = dict(core.DEFAULTS)
        cfg["snippets"] = [{"trigger": "حساب البنك", "text": "الAPI KW123"}]
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", cfg), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="normal"))
        paste.assert_called_once_with("الAPI KW123",
                                      ("gui", "type", "الAPI KW123"))

    def test_sets_vocab_extra_on_client(self):
        app = make_app()
        fake = FakeClient(text="إيميلي الشخصي")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _snippets_cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.vocab_extra, ["إيميلي الشخصي"],
                         "مفتاح الاختصار بيتحط في الـSTT prompt عشان يسمعه الموديل صح")


class TestSnippetPrivacy(unittest.TestCase):
    """F8 (خصوصية): نص الاختصار (IBAN/عنوان/إيميل) عمره ما يندسّ في خانة باسورد."""

    def test_not_expanded_when_secure(self):
        app = make_app()
        fake = FakeClient(text="إيميلي الشخصي")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _snippets_cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit", "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="normal"))
        paste.assert_called_once_with("إيميلي الشخصي", ("secure", "type", "إيميلي الشخصي"))
        hist.assert_not_called()

    def test_not_expanded_in_prompt_mode(self):
        app = make_app()
        fake = FakeClient(text="إيميلي الشخصي")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _snippets_cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(fake.calls, [("transcribe", None), ("prompt",)])
        paste.assert_called_once_with("P:إيميلي الشخصي", ("gui", "type", "P:إيميلي الشخصي"))


class TestClipboardOwned(unittest.TestCase):
    """أي إملاء بيعدّي على الحافظة (لزق أو نسخ) بيتعلم «بتاعنا» — اختباره في unit_inject."""

    def test_mark_clip_owned_stores_seq(self):
        core.mark_clip_owned(42)
        self.assertTrue(core._clip_is_owned(42))
        core.mark_clip_owned(None)           # None = مفيش رقم — ميتضافش
        self.assertFalse(core._clip_is_owned(None))


class TestSttPromptVocabExtra(unittest.TestCase):
    def test_vocab_extra_appended_after_dictionary(self):
        cl = providers.Client("groq", "gsk_test")
        cl.vocab = ["Next.js"]
        cl.vocab_extra = ["إيميلي الشخصي"]
        prompt = cl._stt_prompt("ar")
        self.assertIn("Next.js", prompt)
        self.assertIn("إيميلي الشخصي", prompt)
        # كلمات القاموس قبل مفاتيح الاختصار
        self.assertLess(prompt.index("Next.js"), prompt.index("إيميلي الشخصي"))

    def test_vocab_extra_without_dictionary(self):
        cl = providers.Client("groq", "gsk_test")
        cl.vocab = []
        cl.vocab_extra = ["حساب البنك"]
        prompt = cl._stt_prompt("ar")
        self.assertIn("حساب البنك", prompt)


class TestSnippetsSet(unittest.TestCase):
    def test_validation(self):
        from app_web import Api
        api = Api.__new__(Api)
        items = [
            {"trigger": "  إيميلي  ", "text": "  a@b.com  "},
            {"trigger": "", "text": "x"},
            {"trigger": "   ", "text": "y"},
            "not-a-dict",
            {"trigger": "عنوان", "text": ""},
        ]
        with mock.patch.object(core, "CFG", {}), mock.patch.object(core, "save_config") as sv:
            clean = api.snippets_set(items)
            saved = sv.call_args[0][0]
        self.assertEqual(clean, [{"trigger": "إيميلي", "text": "a@b.com"}])
        self.assertEqual(saved["snippets"], clean)

    def test_returns_truncated_list(self):
        # N7: بنرجّع نفس القايمة المقصوصة اللي اتحفظت (clean[:100]) مش الكاملة —
        # الواجهة لازم تفضل متطابقة مع اللي فعلاً على القرص.
        from app_web import Api
        api = Api.__new__(Api)
        items = [{"trigger": f"ك{i}", "text": f"نص{i}"} for i in range(105)]
        with mock.patch.object(core, "CFG", {}), mock.patch.object(core, "save_config") as sv:
            clean = api.snippets_set(items)
            saved = sv.call_args[0][0]
        self.assertEqual(len(clean), 100)
        self.assertEqual(clean, clean[:100])
        self.assertEqual(saved["snippets"], clean)
        self.assertEqual(saved["snippets"][-1]["trigger"], "ك99")


if __name__ == "__main__":
    unittest.main()


class TestSnippetTriggerCollision(unittest.TestCase):
    def test_renaming_onto_an_existing_trigger_is_rejected_not_dropped(self):
        # A اتعدّل مفتاحه لمفتاح B: الحفظ لازم يترفض، وB ميتمسحش بصمت
        import app_web
        api = app_web.Api.__new__(app_web.Api)
        before = [{"trigger": "رقم الآيبان", "text": "KW81"}, {"trigger": "العنوان", "text": "شارع"}]
        with mock.patch.dict(core.CFG, {"snippets": list(before)}), \
                mock.patch.object(core, "save_config") as save:
            r = api.snippets_set([{"trigger": "العنوان", "text": "جديد"}, {"trigger": "العنوان", "text": "شارع"}])
            self.assertFalse(r["ok"])
            save.assert_not_called()
            self.assertEqual(core.CFG["snippets"], before)
