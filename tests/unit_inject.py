# -*- coding: utf-8 -*-
"""
اختبارات F3 (الحقن الهجين) — winput بـSendInput مزيّف يسجّل الأحداث
ويرجّع العدد اللي «اتحقن» (عشان نحكم على partial/failed)، وcore.paste_text
والترتيب جوّه core.App.process. مفيش أحداث كيبورد حقيقية، ولا شبكة، ولا مفاتيح.
"""
import os
import sys
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core    # noqa: E402
import winput  # noqa: E402


class FakeUser32:
    """
    بيعمل مكان ctypes' user32: SendInput بسجّل الأحداث ويرجّع
    نسبة اللي «اتحقن» — 1.0 = كله، 0.5 = نص، 0.0 = مفيش حاجة.
    """

    def __init__(self, insert_ratio=1.0):
        self.calls = []        # كل نداء: (n المرسوم، الأحداث)
        self.insert_ratio = insert_ratio

    def SendInput(self, n, events, cb):
        self.calls.append((n, events))
        return int(n * self.insert_ratio)


class _FakeU32:
    """محافظ على الـfake أثناء الاختبار: patch لـwinput._user32."""

    def __init__(self, ratio):
        self.fake = FakeUser32(ratio)
        self.patcher = mock.patch.object(winput, "_user32", return_value=self.fake)

    def __enter__(self):
        self.patcher.start()
        return self.fake

    def __exit__(self, *exc):
        self.patcher.stop()


# ── winput.type_text: unicode على دفعات ──────────────────────────────────────
class TestTypeText(unittest.TestCase):
    def test_short_text_events(self):
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.type_text("اب"))
        self.assertEqual(len(fake.calls), 1)
        n, evs = fake.calls[0]
        self.assertEqual(n, 4)                            # حرفين × (down + up)
        for ev in evs:
            self.assertEqual(ev.u.ki.wVk, 0, "unicode: wVk لازم يبقى 0")
            self.assertEqual(ev.u.ki.dwExtraInfo, winput.EMLAA_TAG)
        self.assertEqual(evs[0].u.ki.wScan, ord("ا"))
        self.assertEqual(evs[0].u.ki.dwFlags, winput.KEYEVENTF_UNICODE)
        self.assertEqual(evs[1].u.ki.wScan, ord("ا"))
        self.assertEqual(evs[1].u.ki.dwFlags, winput.KEYEVENTF_UNICODE | winput.KEYEVENTF_KEYUP)
        self.assertEqual(evs[2].u.ki.wScan, ord("ب"))

    def test_chunks_of_64_chars(self):
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.type_text("a" * 100))
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][0], 128)           # 64 حرف × (down + up)
        self.assertEqual(fake.calls[1][0], 72)            # 36 حرف الباقي

    def test_astral_char_never_split_across_chunks(self):
        # 63 حرف عادي + إيموجي (كودي unit اتنين): 64 حرف = دفعة واحدة،
        # والكوبلايجل عمره ما يتقسم على نداءين
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.type_text("a" * 63 + "\U0001F600"))
        self.assertEqual(len(fake.calls), 1)
        evs = fake.calls[0][1]
        self.assertEqual(len(evs), 130)                   # 63×2 + 4
        scans = [e.u.ki.wScan for e in evs[126:]]
        self.assertEqual(scans, [0xD83D, 0xD83D, 0xDE00, 0xDE00])

    def test_partial_send_is_failure_without_resend(self):
        # R1 #12: SendInput أرجع أقل من اللي اتبعت = فشل، ومفيش إعادة إرسال
        with _FakeU32(0.5) as fake:
            self.assertFalse(winput.type_text("a" * 100))
        self.assertEqual(len(fake.calls), 1, "الدفعات اللي بعد الفشل ممن تتبعت")

    def test_zero_inserted_is_failure(self):
        with _FakeU32(0.0) as fake:
            self.assertFalse(winput.type_text("abc"))
        self.assertEqual(len(fake.calls), 1)

    def test_empty_text_is_noop_success(self):
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.type_text(""))
        self.assertEqual(fake.calls, [])


# ── اختصارات اللزق ───────────────────────────────────────────────────────────
class TestPasteShortcuts(unittest.TestCase):
    def test_ctrl_v_sequence(self):
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.paste_ctrl_v())
        n, evs = fake.calls[0]
        self.assertEqual(n, 4)
        self.assertEqual([(e.u.ki.wVk, e.u.ki.dwFlags) for e in evs], [
            (0x11, 0),
            (0x56, 0),
            (0x56, winput.KEYEVENTF_KEYUP),
            (0x11, winput.KEYEVENTF_KEYUP),
        ])
        for e in evs:
            self.assertEqual(e.u.ki.dwExtraInfo, winput.EMLAA_TAG)

    def test_shift_insert_sequence(self):
        with _FakeU32(1.0) as fake:
            self.assertTrue(winput.paste_shift_insert())
        n, evs = fake.calls[0]
        self.assertEqual(n, 4)
        self.assertEqual([(e.u.ki.wVk, e.u.ki.dwFlags) for e in evs], [
            (0x10, 0),
            (0x2D, winput.KEYEVENTF_EXTENDEDKEY),
            (0x2D, winput.KEYEVENTF_EXTENDEDKEY | winput.KEYEVENTF_KEYUP),
            (0x10, winput.KEYEVENTF_KEYUP),
        ])

    def test_partial_send_is_failure(self):
        with _FakeU32(0.5) as fake:
            self.assertFalse(winput.paste_ctrl_v())
            self.assertFalse(winput.paste_shift_insert())
        self.assertEqual(len(fake.calls), 2)


# ── core.paste_text: العقد الجديد placed/failed/handoff ──────────────────────
class TestPasteText(unittest.TestCase):
    def patch_cfg(self, **over):
        cfg = {"auto_paste": True, "insert_method": "auto"}
        cfg.update(over)
        return mock.patch.object(core, "CFG", cfg)

    def test_type_strategy_copies_backup_and_types(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.type_text", return_value=True) as ttype, \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "type", "hello")), "placed")
        copy.assert_called_once_with("hello")
        ttype.assert_called_once_with("hello")

    def test_type_strategy_sendinput_failure_is_failed(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.type_text", return_value=False), \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "type", "hello")), "failed")

    def test_type_strategy_clipboard_failure_not_fatal(self):
        # النسخة الاحتياطية فشلت: الكتابة حرف حرف ما بتعتمدش على الحافظة فبتكمل
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy", side_effect=RuntimeError("no clip")), \
                mock.patch("winput.type_text", return_value=True), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "type", "hello")), "placed")

    def test_ctrl_v_success(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.paste_ctrl_v", return_value=True) as cv, \
                mock.patch("winput.type_text") as ttype, \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "ctrl_v", "hello")), "placed")
        copy.assert_called_once_with("hello")
        cv.assert_called_once_with()
        self.assertFalse(ttype.called)

    def test_ctrl_v_clipboard_failure_is_failed_without_inject(self):
        # اللزق محتاج الحافظة: نشرها فشل = failed، ومفيش محاولة كتابة بديلة
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy", side_effect=RuntimeError("no clip")), \
                mock.patch("winput.paste_ctrl_v") as cv, \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "ctrl_v", "hello")), "failed")
        self.assertFalse(cv.called)

    def test_ctrl_v_sendinput_failure(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.paste_ctrl_v", return_value=False), \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("hello", ("gui", "ctrl_v", "hello")), "failed")

    def test_shift_insert_success(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.paste_shift_insert", return_value=True) as si, \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("echo hi", ("terminal", "shift_insert", "echo hi")),
                             "placed")
        si.assert_called_once_with()

    def test_secure_never_touches_clipboard(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.type_text", return_value=True) as ttype, \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("s3cret", ("secure", "type", "s3cret")), "placed")
        ttype.assert_called_once_with("s3cret")
        self.assertFalse(copy.called, "خانة آمنة: الحافظة ممن تلمس")

    def test_secure_failure_is_failed(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.type_text", return_value=False), \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("s3cret", ("secure", "type", "s3cret")), "failed")
        self.assertFalse(copy.called)

    def test_handoff_copies_and_does_not_inject(self):
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.type_text") as ttype, \
                mock.patch("winput.paste_ctrl_v") as cv:
            self.assertEqual(core.paste_text("hello", ("gui", "handoff", "hello")), "handoff")
        copy.assert_called_once_with("hello")
        self.assertFalse(ttype.called)
        self.assertFalse(cv.called)

    def test_secure_handoff_never_copies(self):
        # مسار دفاعي (مش بيرجع من insert_target): حتى لو جات، الحافظة تصل
        with self.patch_cfg(), \
                mock.patch("pyperclip.copy") as copy:
            self.assertEqual(core.paste_text("x", ("secure", "handoff", "x")), "handoff")
        self.assertFalse(copy.called)

    def test_auto_paste_off_is_handoff_with_copy(self):
        # سلوك قديم: auto_paste مقفول = نسخ + عرض بالواجهة من غير حقن
        with self.patch_cfg(auto_paste=False), \
                mock.patch("pyperclip.copy") as copy, \
                mock.patch("winput.type_text") as ttype:
            self.assertEqual(core.paste_text("hello", ("gui", "type", "hello")), "handoff")
        copy.assert_called_once_with("hello")
        self.assertFalse(ttype.called)

    def test_auto_paste_off_secure_still_no_copy(self):
        with self.patch_cfg(auto_paste=False), \
                mock.patch("pyperclip.copy") as copy:
            self.assertEqual(core.paste_text("s3cret", ("secure", "type", "s3cret")), "handoff")
        self.assertFalse(copy.called)

    def test_missing_target_classifies_on_the_spot(self):
        # العقد القديم (target مش محطوط): التصنيف بيحصل جوه paste_text نفسه
        with self.patch_cfg(), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": False, "class": "TermControl",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.paste_shift_insert", return_value=True) as si, \
                mock.patch.object(core.time, "sleep"):
            self.assertEqual(core.paste_text("echo hi"), "placed")
        si.assert_called_once_with()


# ── has_text_focus: ترفيلة على winput.focused_info بنفس العقد القديم ────────
class TestHasTextFocusWrapper(unittest.TestCase):
    def test_wrapper_returns_editable_verbatim(self):
        for editable in (True, False, None):
            with mock.patch("winput.focused_info",
                            return_value={"is_password": None, "class": "",
                                          "editable": editable}):
                self.assertIs(core.has_text_focus(), editable)


@unittest.skipUnless(os.name == "nt", "UIA — ويندوز بس")
class TestFocusedInfoFailure(unittest.TestCase):
    def test_uia_failure_returns_none_values_and_never_raises(self):
        # فشل UIA = كل القيم None (والسي caller يتعامل «gui» مش «secure» — R1 #1)
        with mock.patch("comtypes.client.CreateObject", side_effect=RuntimeError("uia down")), \
                mock.patch.object(core, "log_error"):
            info = winput.focused_info()
        self.assertEqual(info, {"is_password": None, "class": "", "editable": None})


# ── ترتيب process: التصنيف قبل السجل/الحافظة/الصوت (R1 #1) ───────────────────
class FakeClient:
    """مزوّد وهمي: بيرجّع نص ثابت — زي unit_process."""

    def __init__(self, text="مرحبا بالعالم"):
        self.vocab = []
        self.text = text
        self.last_chat = None

    def engine(self):
        return {"stt": "fake", "stt_model": "m1", "chat": "fake", "chat_model": "m1"}

    def transcribe(self, wav, lang):
        return self.text

    def polish(self, t, profile=None):
        self.last_chat = ("fake", "m1")
        return "p:" + t


def _cfg(**over):
    base = {"polish": True, "bypass_short": False, "bypass_max_words": 3,
            "language": "ar", "dictionary": [], "insert_method": "auto",
            "auto_paste": True, "history_keep_last10": True}
    base.update(over)
    return base


def make_app():
    app = core.App.__new__(core.App)
    app.recording = False
    app.busy = False
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


class TestSecureOrdering(unittest.TestCase):
    """هدف آمن: مفيش حاجة من التسجيل بتاتخذ شكل أثار — بس الدقات تنزل."""

    def test_secure_target_writes_nothing_but_types(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        log = []
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add",
                                  side_effect=lambda *a, **k: log.append("history_add") or 111), \
                mock.patch.object(core, "recording_save",
                                  side_effect=lambda *a, **k: log.append("recording_save")), \
                mock.patch("pyperclip.copy",
                           side_effect=lambda t: log.append("clipboard_copy")), \
                mock.patch("winput.type_text",
                           side_effect=lambda t: log.append("type") or True), \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(log, ["type"],
                         "الهدف الآمن: مفيش سجل/حافظة/صوت — الدقات بس")
        self.assertEqual(app.texts, [], "مفيش on_text")
        self.assertEqual(app.unplaced, [], "مفيش toast للنص الآمن")
        self.assertEqual(app.events[-1], ("done", "normal"))
        self.assertFalse(app.busy)

    def test_uia_failure_falls_back_to_gui_path(self):
        # UIA كله None = سلوك اليوم «gui»: كل الأثار العادية بترجع مكانها
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        log = []

        def on_text_with_log(t):
            app.texts.append(t)
            log.append("on_text")

        app.on_text = on_text_with_log
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": None, "class": "",
                                         "editable": None}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add",
                                  side_effect=lambda *a, **k: log.append("history_add") or 111), \
                mock.patch.object(core, "recording_save",
                                  side_effect=lambda *a, **k: log.append("recording_save")), \
                mock.patch("pyperclip.copy",
                           side_effect=lambda t: log.append("clipboard_copy")), \
                mock.patch("winput.type_text",
                           side_effect=lambda t: log.append("type") or True), \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(log,
                         ["history_add", "on_text", "clipboard_copy", "type",
                          "recording_save"])
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_secure_with_auto_paste_off_skips_typing_and_copy(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        log = []
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg(auto_paste=False)), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add",
                                  side_effect=lambda *a, **k: log.append("history_add") or 111), \
                mock.patch("pyperclip.copy",
                           side_effect=lambda t: log.append("clipboard_copy")), \
                mock.patch("winput.type_text",
                           side_effect=lambda t: log.append("type") or True), \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(log, [], "auto_paste مقفول + خانة آمنة = مفيش أي أثر")
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_secure_type_failure_is_silent(self):
        # الخانة الآمنة مفيش ليها toast حتى لو الدقات فشلت (النص ممن يتعرض)
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        log = []
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add",
                                  side_effect=lambda *a, **k: log.append("history_add") or 111), \
                mock.patch("pyperclip.copy",
                           side_effect=lambda t: log.append("clipboard_copy")), \
                mock.patch("winput.type_text",
                           side_effect=lambda t: log.append("type") or False), \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(log, ["type"])
        self.assertEqual(app.unplaced, [])
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_gui_type_failure_shows_unplaced(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": False, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.type_text", return_value=False), \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.unplaced, ["p:مرحبا بالعالم"])

    def test_multiline_terminal_is_handoff(self):
        # متعدد لحد الترمنال: نسخ + toast، ومفيش حقن خالص (R1 #4)
        app = make_app()
        fake = FakeClient(text="سطر\nسطر")
        app.client = lambda: fake
        log = []

        def on_text_with_log(t):
            app.texts.append(t)
            log.append("on_text")

        app.on_text = on_text_with_log
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": False, "class": "TermControl",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add",
                                  side_effect=lambda *a, **k: log.append("history_add") or 111), \
                mock.patch.object(core, "recording_save",
                                  side_effect=lambda *a, **k: log.append("recording_save")), \
                mock.patch("pyperclip.copy",
                           side_effect=lambda t: log.append("clipboard_copy")), \
                mock.patch("winput.type_text") as ttype, \
                mock.patch("winput.paste_shift_insert") as si, \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        out = "p:سطر\nسطر"
        self.assertEqual(log, ["history_add", "on_text", "clipboard_copy", "recording_save"])
        self.assertFalse(ttype.called)
        self.assertFalse(si.called)
        self.assertEqual(app.unplaced, [out])


if __name__ == "__main__":
    unittest.main()
