# -*- coding: utf-8 -*-
"""
اختبارات أسر الهدف للتعديل في المكان (F6) — winput.capture_target والدوال اللي
حواليه (UIA TextPattern، الحافظة، Ctrl+C، انتظار الموديفايرز)، وآلية تخطي
أرقام التسلسل «بتاعتنا» في core.ClipboardWatcher.

مفيش حافظة حقيقية ولا UIA حقيقي ولا أحداث كيبورد حقيقية — كل حاجة مزيّفة عن
طريق دوال winput القابلة للـpatch (_clipboard32 / _user32 / _focused_element …).
"""
import os
import sys
import hashlib
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core    # noqa: E402
import winput  # noqa: E402


# ── fakes ─────────────────────────────────────────────────────────────────────
class FakeSendInput:
    """مكان user32.SendInput: بسجّل الأحداث ويرجّع نسبة اللي «اتحقن»."""

    def __init__(self, ratio=1.0):
        self.calls = []
        self.ratio = ratio

    def SendInput(self, n, events, cb):
        self.calls.append((n, events))
        return int(n * self.ratio)


class FakeClipUser32:
    """مكان user32 لعمليات الحافظة/المفاتيح: حالات قابلة للتحكم بالكامل."""

    def __init__(self, held=(), foreground=0, seq=0, formats=(), open_ok=True):
        self.held = set(held)          # مفاتيح ماسكة (vks)
        self.foreground = foreground
        self.seq = seq
        self.formats = list(formats)   # صيغ الحافظة بالترتيب
        self.open_ok = open_ok
        self.close_calls = 0

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self.held else 0

    def GetForegroundWindow(self):
        return self.foreground

    def GetClipboardSequenceNumber(self):
        return self.seq

    def OpenClipboard(self, hwnd):
        return self.open_ok

    def CloseClipboard(self):
        self.close_calls += 1
        return 1

    def EnumClipboardFormats(self, prev):
        if prev == 0:
            return self.formats[0] if self.formats else 0
        try:
            i = self.formats.index(prev)
        except ValueError:
            return 0
        return self.formats[i + 1] if i + 1 < len(self.formats) else 0


class FakeTextRange:
    def __init__(self, text):
        self._text = text

    def GetText(self, limit):
        return self._text


class FakeTextSelection:
    def __init__(self, texts):
        self._texts = list(texts)
        self.Length = len(self._texts)

    def GetElement(self, i):
        return FakeTextRange(self._texts[i])


class FakeTextPattern:
    def __init__(self, texts):
        self._sel = FakeTextSelection(texts)

    def GetSelection(self):
        return self._sel


class FakePatternHolder:
    """نتيجة GetCurrentPattern — QueryInterface بيرجّع النمط من غير كوم حقيقي."""

    def __init__(self, pat):
        self._pat = pat

    def QueryInterface(self, iface):
        return self._pat


class FakeElement:
    """عنصر UIA مزيّف: RuntimeId وCurrentClassName ونمط النص بتحديده."""

    def __init__(self, runtime_id=(), texts=(), class_name="Edit", password=False):
        self._rid = list(runtime_id)
        self._holder = FakePatternHolder(FakeTextPattern(texts))
        self.CurrentClassName = class_name
        self._password = password

    def GetRuntimeId(self):
        return self._rid

    def GetCurrentPattern(self, pattern_id):
        return self._holder

    def GetCurrentPropertyValue(self, prop):
        return self._password


class UnknownPasswordElement(FakeElement):
    """عنصر مابيقراش IsPassword (بيرمي) — زي خانة مقدرناش نعرف نوعها."""

    def GetCurrentPropertyValue(self, prop):
        raise RuntimeError("uia property unreadable")


class PasswordUnreadableClassElement(FakeElement):
    """باسورد صح، بس CurrentClassName بيرمي — نختبر إن الباسورد بيتقرا الأول (N1)."""

    @property
    def CurrentClassName(self):
        raise RuntimeError("uia class unreadable")

    @CurrentClassName.setter
    def CurrentClassName(self, v):
        self._cn = v


# ── انتظار الموديفايرز والمقدمة ──────────────────────────────────────────────
class TestModifiersAndForeground(unittest.TestCase):
    def test_modifiers_held_detects_down_keys(self):
        with mock.patch.object(winput, "_clipboard32",
                               return_value=FakeClipUser32(held=(winput.VK_CONTROL,))):
            self.assertTrue(winput.modifiers_held())
        with mock.patch.object(winput, "_clipboard32", return_value=FakeClipUser32()):
            self.assertFalse(winput.modifiers_held())

    def test_wait_modifiers_released_true_when_clear(self):
        with mock.patch.object(winput, "_clipboard32", return_value=FakeClipUser32()), \
                mock.patch.object(winput.time, "sleep"):
            self.assertTrue(winput.wait_modifiers_released(timeout=0.01))

    def test_wait_modifiers_released_times_out_while_held(self):
        with mock.patch.object(winput, "_clipboard32",
                               return_value=FakeClipUser32(held=(winput.VK_MENU,))), \
                mock.patch.object(winput.time, "sleep"):
            self.assertFalse(winput.wait_modifiers_released(timeout=0.01))

    def test_foreground_hwnd_reads_from_user32(self):
        with mock.patch.object(winput, "_clipboard32",
                               return_value=FakeClipUser32(foreground=12345)):
            self.assertEqual(winput.foreground_hwnd(), 12345)

    def test_foreground_hwnd_zero_on_failure(self):
        with mock.patch.object(winput, "_clipboard32", side_effect=RuntimeError("no user32")):
            self.assertEqual(winput.foreground_hwnd(), 0)


# ── حقن Ctrl+C ───────────────────────────────────────────────────────────────
class TestCopySelection(unittest.TestCase):
    def test_copy_selection_sends_ctrl_c_tagged(self):
        with mock.patch.object(winput, "_user32", return_value=FakeSendInput(1.0)) as u32:
            self.assertTrue(winput.copy_selection())
        n, evs = u32.return_value.calls[0]
        self.assertEqual([(e.u.ki.wVk, e.u.ki.dwFlags) for e in evs], [
            (winput.VK_CONTROL, 0),
            (winput.VK_C, 0),
            (winput.VK_C, winput.KEYEVENTF_KEYUP),
            (winput.VK_CONTROL, winput.KEYEVENTF_KEYUP),
        ])
        for e in evs:
            self.assertEqual(e.u.ki.dwExtraInfo, winput.EMLAA_TAG)

    def test_copy_selection_partial_send_is_failure(self):
        with mock.patch.object(winput, "_user32", return_value=FakeSendInput(0.5)):
            self.assertFalse(winput.copy_selection())


# ── صيغ الحافظة ──────────────────────────────────────────────────────────────
class TestClipboardFormats(unittest.TestCase):
    def test_clipboard_text_formats_filters_non_text(self):
        fake = FakeClipUser32(formats=[winput.CF_TEXT, 49999, winput.CF_UNICODETEXT])
        with mock.patch.object(winput, "_clipboard32", return_value=fake):
            self.assertEqual(winput.clipboard_text_formats(),
                             [winput.CF_TEXT, winput.CF_UNICODETEXT])

    def test_clipboard_text_formats_empty(self):
        with mock.patch.object(winput, "_clipboard32", return_value=FakeClipUser32(formats=[])):
            self.assertEqual(winput.clipboard_text_formats(), [])

    def test_clipboard_safe_for_text_allows_text_and_empty(self):
        with mock.patch.object(winput, "_clipboard32",
                               return_value=FakeClipUser32(formats=[winput.CF_UNICODETEXT])):
            self.assertTrue(winput._clipboard_safe_for_text())
        with mock.patch.object(winput, "_clipboard32", return_value=FakeClipUser32(formats=[])):
            self.assertTrue(winput._clipboard_safe_for_text())

    def test_clipboard_safe_rejects_non_text_content(self):
        fake = FakeClipUser32(formats=[winput.CF_UNICODETEXT, 49999])
        with mock.patch.object(winput, "_clipboard32", return_value=fake):
            self.assertFalse(winput._clipboard_safe_for_text())


# ── UIA TextPattern ───────────────────────────────────────────────────────────
class TestUiaSelection(unittest.TestCase):
    def test_selection_text_joins_ranges(self):
        el = FakeElement(texts=["abc", "", "def"])
        self.assertEqual(winput._selection_text(el), "abcdef")

    def test_selection_text_empty_when_no_pattern(self):
        class NoPatternElement(FakeElement):
            def GetCurrentPattern(self, pattern_id):
                return None
        # None = النمط مش مدعوم (الخطة البديلة بالحافظة مسموحة)، مش «مفيش تحديد»
        self.assertIsNone(winput._selection_text(NoPatternElement()))

    def test_runtime_id_converts_to_tuple(self):
        self.assertEqual(winput._runtime_id(FakeElement(runtime_id=[5, 6])), (5, 6))
        self.assertEqual(winput._runtime_id(FakeElement(runtime_id=[])), ())


# ── الخطة البديلة: أسر التحديد بالحافظة ──────────────────────────────────────
class FakeClipboard:
    """حافظة مزيّفة برقم تسلسل: كل كتابة (من البرنامج التاني أو مننا) بتزوّد الرقم."""

    def __init__(self, text, copy_result=None, user_copy_during_poll=None):
        self.text, self.seq = text, 100
        self.copy_result = copy_result            # اللي «البرنامج» بينسخه لما نحقن Ctrl+C
        self.user_copy = user_copy_during_poll    # المستخدم بينسخ حاجة جديدة قبل ما نرجّع
        self.events = []
        self.copied = False

    def read(self):
        self.events.append(("read", self.seq))
        text = self.text
        if self.copied and self.user_copy is not None:
            self.write(self.user_copy)          # المستخدم نسخ بعد ما قرينا النص المحدد
            self.user_copy = None
        return text

    def write(self, t):
        self.text, self.seq = t, self.seq + 1
        return True

    def ctrl_c(self):
        if self.copy_result is not None:
            self.write(self.copy_result)
            self.copied = True
        return True

    def run(self, **extra):
        patches = [mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True),
                   mock.patch.object(winput, "_read_clipboard_text", side_effect=self.read),
                   mock.patch.object(winput, "_write_clipboard_text", side_effect=self.write),
                   mock.patch.object(winput, "_clipboard_sequence", side_effect=lambda: self.seq),
                   mock.patch.object(winput, "wait_modifiers_released", return_value=True),
                   mock.patch.object(winput, "copy_selection", side_effect=self.ctrl_c),
                   mock.patch.object(winput, "_mark_owned",
                                     side_effect=lambda s: self.events.append(("mark", s))),
                   mock.patch.object(winput.time, "sleep")]
        patches += [mock.patch.object(winput.time, k, **v) for k, v in extra.items()]
        for p in patches:
            p.start()
        try:
            return winput._selection_via_clipboard()
        finally:
            for p in patches:
                p.stop()

    def marked(self):
        return [s for kind, s in self.events if kind == "mark"]


class TestSelectionViaClipboard(unittest.TestCase):
    def test_roundtrip_returns_selection_and_restores_old_text(self):
        clip = FakeClipboard("old", copy_result="selection")
        self.assertEqual(clip.run(), "selection")
        self.assertEqual(clip.text, "old")                  # رجّعنا الحافظة زي ما كانت
        self.assertEqual(clip.marked(), [101, 102])         # نسخة Ctrl+C والإرجاع اتوسموا

    def test_newer_user_copy_is_never_overwritten(self):
        # المستخدم نسخ حاجة بعد Ctrl+C بتاعنا — نسخته الأحدث لازم تفضل (R1 #7)
        clip = FakeClipboard("old", copy_result="selection", user_copy_during_poll="user-new")
        clip.run()
        self.assertEqual(clip.text, "user-new")

    def test_timeout_leaves_clipboard_untouched(self):
        # مفيش تحديد اتنسخ: الحافظة متتكتبش ورقم التسلسل بتاع المستخدم ميتوسمش
        clip = FakeClipboard("old", copy_result=None)
        # M4: _selection_via_clipboard دلوقتي بينادي core.suppress_clip_watch قبل
        # الحقن — نداء monotonic زيادة (أول قيمة بتستهلكها الكبس)، فبنزوّد واحدة.
        self.assertEqual(clip.run(monotonic={"side_effect": [0.0, 0.0, 10.0]}), "")
        self.assertEqual((clip.text, clip.seq, clip.marked()), ("old", 100, []))

    def test_copy_sequence_marked_before_reading(self):
        # الوسم قبل القراية — غير كده الـwatcher ممكن يلحق يسجّل النص المحدد
        clip = FakeClipboard("old", copy_result="selection")
        clip.run()
        after_copy = [e for e in clip.events if e[1] == 101]
        self.assertEqual(after_copy[0], ("mark", 101))

    def test_unsafe_clipboard_skips_without_touching(self):
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=False), \
                mock.patch.object(winput, "copy_selection") as copy, \
                mock.patch.object(winput, "_read_clipboard_text") as read:
            self.assertEqual(winput._selection_via_clipboard(), "")
        self.assertFalse(copy.called)
        self.assertFalse(read.called)

    def test_copy_failure_returns_empty(self):
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "_read_clipboard_text", return_value="old"), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_clipboard_sequence", return_value=5), \
                mock.patch.object(winput, "copy_selection", return_value=False):
            self.assertEqual(winput._selection_via_clipboard(), "")

    def test_cancel_before_inject_returns_empty_and_never_touches(self):
        # M2: الاتلغاء قبل الحقن → منحقنش Ctrl+C ومنقراش الحافظة خالص
        ev = threading.Event()
        ev.set()
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "copy_selection") as copy, \
                mock.patch.object(winput, "_read_clipboard_text") as read:
            self.assertEqual(winput._selection_via_clipboard(cancel=ev), "")
        self.assertFalse(copy.called)
        self.assertFalse(read.called)

    def test_cancel_after_inject_still_restores(self):
        # N4b: الاتلغاء بعد الحقن لازم برضه يرجّع الحافظة — منسيبهاش على التحديد.
        ev = threading.Event()

        def mark_then_change(seq_before):
            ev.set()
            return 101

        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "_read_clipboard_text", side_effect=["old", "sel"]), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_clipboard_sequence", return_value=101), \
                mock.patch.object(winput, "copy_selection", return_value=True), \
                mock.patch.object(winput, "_wait_clipboard_change", side_effect=mark_then_change), \
                mock.patch.object(winput, "_write_clipboard_text") as write, \
                mock.patch.object(winput, "_mark_owned"), \
                mock.patch.object(core, "suppress_clip_watch"), \
                mock.patch.object(winput.time, "sleep"):
            out = winput._selection_via_clipboard(cancel=ev)
        self.assertEqual(out, "")           # اتلغينا → منرجّعش التحديد
        self.assertTrue(write.called, "الحافظة لازم تترجّع حتى بعد الإلغاء")

    def test_read_clipboard_text_returns_none_on_failure(self):
        # M3: القراية بتفرّق الفشل (None) عن الفاضي ('') — مش نفس القيمة
        with mock.patch("pyperclip.paste", side_effect=RuntimeError("no clip")):
            self.assertIsNone(winput._read_clipboard_text())

    def test_old_read_failure_never_injects_ctrl_c(self):
        # N4a: قراية القديم فشلت (None) = مفيش سناب شوت نرجع بيه — منحقنش Ctrl+C
        # خالص (منعرفش نرجع الحافظة لاحقًا، فممن نكتب فوقها).
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "_read_clipboard_text", return_value=None), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_clipboard_sequence", return_value=100), \
                mock.patch.object(winput, "copy_selection") as copy, \
                mock.patch.object(winput, "_wait_clipboard_change", return_value=101), \
                mock.patch.object(winput, "_write_clipboard_text") as write, \
                mock.patch.object(winput, "_mark_owned"), \
                mock.patch.object(core, "suppress_clip_watch"), \
                mock.patch.object(winput.time, "sleep"):
            out = winput._selection_via_clipboard()
        self.assertEqual(out, "")
        self.assertFalse(copy.called, "مفيش Ctrl+C لما القراية فشلت")
        self.assertFalse(write.called)

    def test_sequence_change_after_read_fails(self):
        # N3: بعد قراية النص المحدد، لو رقم التسلسل اتغيّر (حد تاني كتب في النص)
        # → نفشل من غير ما نرجّع الحافظة ولا نرجع التحديد.
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "_read_clipboard_text", side_effect=["old", "sel"]), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_clipboard_sequence", side_effect=[100, 102, 102]), \
                mock.patch.object(winput, "copy_selection", return_value=True), \
                mock.patch.object(winput, "_wait_clipboard_change", return_value=101), \
                mock.patch.object(winput, "_write_clipboard_text") as write, \
                mock.patch.object(winput, "_mark_owned"), \
                mock.patch.object(core, "suppress_clip_watch"), \
                mock.patch.object(winput.time, "sleep"):
            out = winput._selection_via_clipboard()
        self.assertEqual(out, "")
        self.assertFalse(write.called, "مفيش رجوع لما التسلسل اتغيّر")

    def test_capture_suppresses_watcher_before_inject(self):
        # M4: كبس المراقب لازم يحصل قبل حقن Ctrl+C (قبل copy_selection)
        order = []
        with mock.patch.object(winput, "_clipboard_safe_for_text", return_value=True), \
                mock.patch.object(winput, "_read_clipboard_text", return_value="old"), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_clipboard_sequence", return_value=5), \
                mock.patch.object(winput, "copy_selection", side_effect=lambda: order.append("copy") or True), \
                mock.patch.object(winput, "_wait_clipboard_change", return_value=6), \
                mock.patch.object(winput, "_mark_owned"), \
                mock.patch.object(core, "suppress_clip_watch",
                                  side_effect=lambda s: order.append("suppress")), \
                mock.patch.object(winput.time, "sleep"):
            winput._selection_via_clipboard()
        self.assertEqual(order, ["suppress", "copy"])


# ── كبس مراقب الحافظة (M4) ───────────────────────────────────────────────────
class TestClipWatchSuppression(unittest.TestCase):
    def setUp(self):
        core._clip_suppress_until = 0.0

    def test_suppress_blocks_until_deadline(self):
        with mock.patch.object(core.time, "monotonic", return_value=100.0):
            core.suppress_clip_watch(2.0)
        with mock.patch.object(core.time, "monotonic", return_value=101.9):
            self.assertTrue(core._clip_watch_suppressed())
        with mock.patch.object(core.time, "monotonic", return_value=102.1):
            self.assertFalse(core._clip_watch_suppressed())

    def test_no_suppression_by_default(self):
        with mock.patch.object(core.time, "monotonic", return_value=0.0):
            self.assertFalse(core._clip_watch_suppressed())


# ── capture_target ────────────────────────────────────────────────────────────
class TestCaptureTarget(unittest.TestCase):
    def test_reads_uia_selection_and_runtime_id(self):
        el = FakeElement(runtime_id=[1, 2, 3], texts=["مرحبا", " بالعالم"],
                         class_name="Edit")
        with mock.patch.object(winput, "foreground_hwnd", return_value=42), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertEqual(out["hwnd"], 42)
        self.assertEqual(out["runtime_id"], (1, 2, 3))
        self.assertEqual(out["class"], "Edit")
        self.assertEqual(out["selection"], "مرحبا بالعالم")
        self.assertEqual(out["selection_hash"],
                         hashlib.sha1("مرحبا بالعالم".encode("utf-8")).hexdigest())
        self.assertFalse(fallback.called)

    def test_falls_back_to_clipboard_when_uia_pattern_unsupported(self):
        el = FakeElement(runtime_id=[9], texts=[], class_name="Edit")
        with mock.patch.object(winput, "foreground_hwnd", return_value=1), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_text", return_value=None), \
                mock.patch.object(winput, "_selection_via_clipboard",
                                  return_value="from-clip") as fallback:
            out = winput.capture_target()
        self.assertEqual(out["selection"], "from-clip")
        fallback.assert_called_once_with(None)
        self.assertNotIn("_uia_unsupported", out)

    def test_uia_empty_selection_never_injects_ctrl_c(self):
        # UIA شغّال وقال «مفيش تحديد»: Ctrl+C في VS Code كان هينسخ السطر كله
        el = FakeElement(runtime_id=[9], texts=[], class_name="Edit")
        with mock.patch.object(winput, "foreground_hwnd", return_value=1), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_text", return_value=""), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_clipboard_when_uia_element_unavailable(self):
        # N1: العنصر مش متاح → نستنى الموديفايرز ونعيد قراية العنصر مرة؛ لو لسه
        # مش متاح → نسمح بالخطة البديلة.
        with mock.patch.object(winput, "foreground_hwnd", return_value=5), \
                mock.patch.object(winput, "_focused_element", side_effect=[None, None]), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_selection_via_clipboard",
                                  return_value="clip-text"):
            out = winput.capture_target()
        self.assertEqual(out["selection"], "clip-text")
        self.assertEqual(out["runtime_id"], ())
        self.assertEqual(out["class"], "")

    def test_element_none_after_wait_password_refused(self):
        # N1: العنصر مش متاح → بعد استنى الموديفايرز وإعادة قراية العنصر، لو رجع
        # خانة باسورد → رفض من غير خطة الحافظة.
        el = FakeElement(runtime_id=[1], texts=["سر"], password=True)
        with mock.patch.object(winput, "foreground_hwnd", return_value=42), \
                mock.patch.object(winput, "_focused_element", side_effect=[None, el]), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertTrue(out["password"])
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_element_none_modifiers_stuck_no_fallback(self):
        # N1: العنصر مش متاح والموديفايرز لسه ماسكين → مفيش خطة حافظة.
        with mock.patch.object(winput, "foreground_hwnd", return_value=5), \
                mock.patch.object(winput, "_focused_element", return_value=None), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=False), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_password_checked_before_classname_read(self):
        # N1: لو CurrentClassName بيرمي، قراية الباسورد لسه بتحصل الأول — من
        # غيرها كانت الخطة البديلة هتشتغل على خانة باسورد.
        el = PasswordUnreadableClassElement(runtime_id=[1], texts=["سر"], password=True)
        with mock.patch.object(winput, "foreground_hwnd", return_value=42), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertTrue(out["password"])
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_password_field_refused_without_fallback(self):
        # M1: خانة باسورد → password=True وتحديد فاضي ومنجربش خطة الحافظة
        el = FakeElement(runtime_id=[1, 2], texts=["سر"], class_name="Edit", password=True)
        with mock.patch.object(winput, "foreground_hwnd", return_value=42), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertTrue(out["password"])
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_unreadable_password_refused_without_fallback(self):
        # M1: مقدرناش نقرا IsPassword → بنتعامل معاها رفض جوه capture بس
        el = UnknownPasswordElement(runtime_id=[1], texts=["سر"])
        with mock.patch.object(winput, "foreground_hwnd", return_value=42), \
                mock.patch.object(winput, "_focused_element", return_value=el), \
                mock.patch.object(winput, "_selection_via_clipboard") as fallback:
            out = winput.capture_target()
        self.assertTrue(out["password"])
        self.assertEqual(out["selection"], "")
        fallback.assert_not_called()

    def test_never_raises_on_total_failure(self):
        with mock.patch.object(winput, "foreground_hwnd", side_effect=RuntimeError("boom")), \
                mock.patch.object(winput, "_focused_element", side_effect=RuntimeError("uia")), \
                mock.patch.object(winput, "wait_modifiers_released", return_value=True), \
                mock.patch.object(winput, "_selection_via_clipboard",
                                  side_effect=RuntimeError("clip")), \
                mock.patch.object(core, "log_error"):
            out = winput.capture_target()
        self.assertEqual(out, {"hwnd": 0, "runtime_id": (), "class": "",
                               "selection": "", "selection_hash": ""})


# ── مراقب الحافظة: إعادة قراية رقم التسلسل بعد القراية (N3) ──────────────────
class FakeWatchUser32:
    """user32 مزيّف لتكرار واحد من core.ClipboardWatcher — بيحاكي حالة الحافظة
    ورا المراقب من غير أي نداء Win32 حقيقي."""

    EXCL_FMT = 49999

    def __init__(self, seq=5, seq_after_read=5, excluded=False, has_text=True):
        self.seq = seq
        self.seq_after_read = seq_after_read
        self.excluded = excluded
        self.has_text = has_text

    def GetClipboardSequenceNumber(self):
        return self.seq

    def IsClipboardFormatAvailable(self, fmt):
        return self.excluded if fmt == self.EXCL_FMT else self.has_text

    def OpenClipboard(self, hwnd):
        return True

    def CloseClipboard(self):
        return True


class TestClipboardWatcherRecheck(unittest.TestCase):
    """N3: المراقب بيعيد قراية رقم التسلسل بعد قراية النص — لو اتغيّر، القراية
    بتتجاهل ومبيقدمش last عشان التكرار الجاي يعيد تقييم الرقم الحالي."""

    def test_sequence_change_during_read_discards(self):
        u32 = FakeWatchUser32(seq=5, seq_after_read=6)
        w = core.ClipboardWatcher()
        recorded = []
        w.on_new = recorded.append

        def read(u, k, fmt):
            u.seq = u.seq_after_read          # برنامج تاني كتب جوّه قرايتنا
            return "hello"

        with mock.patch.object(core, "_clip_watch_suppressed", return_value=False), \
                mock.patch.object(core, "_clip_is_owned", return_value=False), \
                mock.patch.object(core, "CFG", {"clipboard_history": True}), \
                mock.patch.object(core, "_clip_read_text", side_effect=read), \
                mock.patch.object(core, "clip_add") as add, \
                mock.patch.object(core, "_foreground_app", return_value=""):
            new_last = w._watch_once(u32, object(), u32.EXCL_FMT, 13, last=4)
        self.assertEqual(new_last, 4, "last مقدمش — بنعيد التقييم من أول")
        add.assert_not_called()
        self.assertEqual(recorded, [])

    def test_sequence_stable_records_and_advances(self):
        u32 = FakeWatchUser32(seq=5, seq_after_read=5)
        w = core.ClipboardWatcher()
        recorded = []
        w.on_new = recorded.append
        with mock.patch.object(core, "_clip_watch_suppressed", return_value=False), \
                mock.patch.object(core, "_clip_is_owned", return_value=False), \
                mock.patch.object(core, "CFG", {"clipboard_history": True}), \
                mock.patch.object(core, "_clip_read_text", return_value="hello"), \
                mock.patch.object(core, "clip_add", return_value={"id": 1}) as add, \
                mock.patch.object(core, "_foreground_app", return_value=""):
            new_last = w._watch_once(u32, object(), u32.EXCL_FMT, 13, last=4)
        self.assertEqual(new_last, 5)
        add.assert_called_once()
        self.assertEqual(recorded, [{"id": 1}])


# ── أرقام تسلسل الحافظة «بتاعتنا» (core) ────────────────────────────────────
class TestOwnedClipSeqs(unittest.TestCase):
    def setUp(self):
        core._owned_clip_seqs.clear()

    def test_mark_and_check_owned(self):
        core.mark_clip_owned(101)
        self.assertTrue(core._clip_is_owned(101))
        self.assertFalse(core._clip_is_owned(102))

    def test_owned_seqs_are_bounded(self):
        # deque بـmaxlen=64: أقدم الأرقام تطلع لما نتجاوز الحد
        for i in range(100):
            core.mark_clip_owned(i)
        self.assertFalse(core._clip_is_owned(0))
        self.assertTrue(core._clip_is_owned(99))

    def test_mark_ignores_non_int(self):
        core.mark_clip_owned("abc")
        self.assertFalse(core._clip_is_owned("abc"))


if __name__ == "__main__":
    unittest.main()
