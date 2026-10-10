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
        # F6: الحقن الجزئي = فشل، ومعاه نداء متابعة بيبعث key-up للمفاتيح الماسكة
        with _FakeU32(0.5) as fake:
            self.assertFalse(winput.paste_ctrl_v())
            self.assertFalse(winput.paste_shift_insert())
        # كل زرار: نداء الحقن (4 أحداث → اتحقن 2) + نداء key-up متابعة (2)
        self.assertEqual(len(fake.calls), 4)

    def test_partial_insert_releases_held_modifier(self):
        # F6: SendInput حقن Ctrl↓ بس (1 من 4) — من غير متابعة كان Ctrl يفضل
        # ماسك. المتابعة لازم تحتوي key-up للموديفاير اللي اتدس.
        with _FakeU32(0.25) as fake:          # 4 * 0.25 = 1 → أول حدث بس
            self.assertFalse(winput.paste_ctrl_v())
        self.assertGreaterEqual(len(fake.calls), 2, "مفيش نداء متابعة للـkey-up")
        _, evs2 = fake.calls[1]
        self.assertTrue(any(e.u.ki.wVk == winput.VK_CONTROL and
                            (e.u.ki.dwFlags & winput.KEYEVENTF_KEYUP) for e in evs2),
                        "المتابعة لازم فيها key-up لـCtrl")
        for e in evs2:
            self.assertEqual(e.u.ki.dwExtraInfo, winput.EMLAA_TAG)


# ── core.paste_text: الإملاء مبيتنسخش للحافظة (غير لما الكتابة التلقائية مقفولة) ──
class _Clipboard:
    """حافظة وهمية على حدود Win32 (winput): بتسجّل الكتابة وبتزوّد رقم التسلسل."""

    def __init__(self, text="OLD", safe=True, fail_copy=False):
        self.text, self.safe, self.fail_copy = text, safe, fail_copy
        self.seq, self.writes = 1, []
        self.read_fails = False
        self.responsive = True          # البرنامج اللي بنلزق فيه بيرد (مش مهنّج)

    def read(self):
        return None if self.read_fails else self.text

    def sequence(self):
        return self.seq

    def write(self, text):
        self.text, self.seq = text, self.seq + 1
        self.writes.append(text)

    def copy(self, text):
        if self.fail_copy:
            raise OSError("no clip")
        self.write(text)

    def write_if(self, text, expect_seq=None):
        """winput.write_clipboard_text: الفحص والكتابة ذرّيين (الحافظة مفتوحة طولهم)."""
        if expect_seq is not None and self.seq != expect_seq:
            return False
        self.copy(text)
        return True

    def patches(self):
        return [mock.patch("winput.write_clipboard_text",
                           side_effect=lambda t, s=None: self.write_if(t, s)),
                mock.patch("winput.foreground_hwnd", return_value=42),
                mock.patch("winput.wait_responsive", side_effect=lambda h, ms: self.responsive),
                mock.patch("winput._clipboard_safe_for_text", side_effect=lambda: self.safe),
                mock.patch("winput._read_clipboard_text", side_effect=lambda: self.read()),
                mock.patch("winput._clipboard_sequence", side_effect=lambda: self.sequence()),
                mock.patch.object(core, "mark_clip_owned"),
                mock.patch.object(core, "suppress_clip_watch"),
                mock.patch.object(core, "log_error")]


class TestPasteText(unittest.TestCase):
    def setUp(self):
        self.clip = _Clipboard()
        self.sleep = mock.Mock()

    def run_paste(self, target, guard=None, inject=True, on_paste=None, **cfg_over):
        """on_paste = اللي بيحصل لحظة Ctrl+V (بديل return_value)."""
        cfg = {"auto_paste": True, "insert_method": "auto"}
        cfg.update(cfg_over)
        self.ttype = mock.Mock(return_value=inject)
        self.cv = mock.Mock(side_effect=on_paste) if on_paste else mock.Mock(return_value=inject)
        self.si = mock.Mock(return_value=inject)
        patches = self.clip.patches() + [
            mock.patch.object(core.time, "sleep", self.sleep),
            mock.patch.object(core, "CFG", cfg),
            mock.patch("winput.type_text", self.ttype),
            mock.patch("winput.paste_ctrl_v", self.cv),
            mock.patch("winput.paste_shift_insert", self.si)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return core.paste_text(target[2], target, guard=guard)

    def test_typed_text_never_touches_clipboard(self):
        self.assertEqual(self.run_paste(("gui", "type", "hello")), "placed")
        self.ttype.assert_called_once_with("hello")
        self.assertEqual((self.clip.writes, self.clip.text), ([], "OLD"))

    def test_type_failure_is_failed_without_copy(self):
        self.assertEqual(self.run_paste(("gui", "type", "hello"), inject=False), "failed")
        self.assertEqual(self.clip.writes, [])

    def test_ctrl_v_pastes_then_restores_previous_clipboard(self):
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "placed")
        self.cv.assert_called_once_with()
        self.assertEqual(self.clip.writes, ["hello", "OLD"])
        self.assertEqual(self.clip.text, "OLD")

    def test_restore_waits_for_target_to_read_clipboard(self):
        # الرجوع بدري = البرنامج التاني يلزق القديم: لازم انتظار بعد اللزق وقبل الرجوع
        order = []
        self.sleep.side_effect = lambda s: order.append(("sleep", s))
        self.clip.copy = lambda t: order.append(("copy", t)) or self.clip.write(t)
        self.run_paste(("gui", "ctrl_v", "hello"), on_paste=lambda: order.append("paste") or True)
        self.assertEqual(order[order.index("paste"):],
                         ["paste", ("sleep", core.PASTE_SETTLE_SECONDS), ("copy", "OLD")])

    def test_hung_target_keeps_dictation_instead_of_restoring(self):
        # PR #14 (Codex P1): البرنامج مهنّج وممكن لسه ما قراش الحافظة — الرجوع كان
        # هيخلّيه يلزق نسخة المستخدم القديمة (ممكن تبقى حاجة حسّاسة) بدل الإملاء
        self.clip.responsive = False
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "placed")
        self.assertEqual(self.clip.text, "hello")
        self.assertEqual(self.clip.writes, ["hello"])
        self.sleep.assert_called_once_with(0.12)     # انتظار الفوكس بس — مفيش انتظار رجوع

    def test_user_copy_during_paste_is_not_overwritten(self):
        # المستخدم نسخ حاجة في النص (رقم التسلسل اتغيّر) — نسخته الأحدث تفضل
        def paste_while_user_copies():
            self.clip.write("USER")
            return True

        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello"),
                                        on_paste=paste_while_user_copies), "placed")
        self.assertEqual(self.clip.text, "USER")

    def test_dictation_on_clipboard_is_marked_owned(self):
        # صفحة الحافظة متسجّلش الإملاء ولا نص المستخدم القديم كنسخة جديدة: الكتابتين
        # (المؤقتة والرجوع) المراقب مكبوس قبلهم ومتعلّمين «بتاعنا» بعدهم
        self.run_paste(("gui", "ctrl_v", "hello"))
        self.assertEqual(core.suppress_clip_watch.call_count, 2)
        owned = [c.args[0] for c in core.mark_clip_owned.call_args_list]
        self.assertEqual(owned, [2, 3])

    def test_non_text_clipboard_single_line_is_typed_instead(self):
        # صورة/ملفات على الحافظة منقدرش نرجّعها — السطر الواحد بيتكتب ومنلمسهاش
        self.clip.safe = False
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "a long single line")), "placed")
        self.ttype.assert_called_once_with("a long single line")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.writes, [])

    def test_remote_paste_does_not_restore(self):
        # RDP/VM: مزامنة الحافظة متأخرة — الرجوع ممكن يخلّي الجهاز التاني يلزق القديم
        self.run_paste(("remote", "ctrl_v", "line1\nline2"))
        self.assertEqual(self.clip.writes, ["line1\nline2"])

    def test_remote_paste_does_not_write_over_a_newer_copy(self):
        # PR #14 (Codex P2): RDP/VM من غير رجوع — بس برضه منكتبش فوق نسخة جت بعد ما بدأنا
        reads = []

        def sequence():
            reads.append(self.clip.seq)
            if len(reads) == 1:
                self.clip.write("SYNC")         # المزامنة كتبت بعد أول قراية للرقم
            return reads[-1]

        self.clip.sequence = sequence
        self.assertEqual(self.run_paste(("remote", "ctrl_v", "line1\nline2")), "handoff")
        self.assertEqual(self.clip.writes, ["SYNC"], "الإملاء ميتكتبش فوق النسخة الأحدث")
        self.cv.assert_not_called()

    def test_no_restorable_snapshot_hands_off_without_touching_clipboard(self):
        # PR #14 (Codex P1 / CodeRabbit): صورة/ملفات (متعدد أو ترمنال) أو قراية فاشلة =
        # مفيش نسخة نرجّع بيها — اللزق كان هيمسح محتوى المستخدم، فالرسالة بزرار نسخ أأمن
        cases = [(dict(safe=False), ("gui", "ctrl_v", "line1\nline2")),
                 (dict(safe=False), ("terminal", "shift_insert", "echo hi")),
                 (dict(read_fails=True), ("gui", "ctrl_v", "line1\nline2"))]
        for state, target in cases:
            self.clip = _Clipboard()
            for k, v in state.items():
                setattr(self.clip, k, v)
            self.assertEqual(self.run_paste(target), "handoff", (state, target))
            self.assertEqual(self.clip.writes, [], (state, target))
            self.cv.assert_not_called()
            self.si.assert_not_called()

    def test_external_write_right_after_ours_is_not_pasted(self):
        # PR #14 (Codex P2): برنامج تاني كتب بعد نسختنا على طول — رقمه ميتعلّمش «بتاعنا»،
        # ومنلزقش محتواه ولا نرجّع القديم فوقه
        def ours_then_external(t):
            self.clip.write(t)
            self.clip.write("EXT")

        self.clip.copy = ours_then_external
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.text, "EXT")
        core.mark_clip_owned.assert_not_called()

    def _reads(self, *results):
        """قراية الحافظة بالترتيب: نص، أو None (القراية فشلت)، أو دالة بتتنفّذ وترجّع نص."""
        calls = iter(results)

        def read():
            r = next(calls, self.clip.text)
            return r() if callable(r) else r

        self.clip.read = read

    def test_failed_read_back_still_restores_snapshot(self):
        # PR #14 (Codex P1): القراية بعد نسختنا فشلت والرقم ثابت = مفيش حد كتب بعدنا —
        # النسخة بتاعتنا: نلزق ونرجّع حافظة المستخدم بدل ما تضيع
        self._reads("OLD", None)
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "placed")
        self.cv.assert_called_once_with()
        self.assertEqual(self.clip.text, "OLD")

    def test_non_text_written_after_ours_is_not_taken_as_ours(self):
        # PR #14 (Codex P2): برنامج حط صورة بعد نسختنا على طول — القراية بترجع None والرقم
        # ثابت، بس الصيغ مش نص بس: النسخة مش بتاعتنا، فمنلزقش ولا نرجّع فوقها
        def ours_then_image(t):
            self.clip.write(t)
            self.clip.write("<image>")
            self.clip.safe, self.clip.read_fails = False, True

        self.clip.copy = ours_then_image
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "line1\nline2")), "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.text, "<image>")

    def test_copy_between_snapshot_and_write_is_kept(self):
        # PR #14 (Codex P2): المستخدم نسخ بعد ما قرينا الحافظة وقبل ما نكتب — منكتبش فوقه
        def snapshot_then_user_copies():
            self.clip.write("USER")
            return "OLD"

        self._reads(snapshot_then_user_copies)
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.writes, ["USER"])
        self.assertEqual(self.clip.text, "USER")

    def test_external_write_before_paste_is_not_pasted(self):
        # حد كتب في الحافظة بين نسختنا والضغطة (وقت الفحص) — منلزقش حاجة مش بتاعتنا
        def guard_while_external_writes():
            self.clip.write("EXT")
            return True

        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello"),
                                        guard=guard_while_external_writes), "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.text, "EXT")

    def test_paste_clipboard_failure_hands_off_without_inject(self):
        # نسخة الإملاء منزلتش على الحافظة = ولا حاجة نلزقها: الرسالة بزرار نسخ
        self.clip.fail_copy = True
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello")), "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.text, "OLD")

    def test_paste_sendinput_failure_is_failed_and_restores(self):
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello"), inject=False), "failed")
        self.assertEqual(self.clip.text, "OLD")

    def test_shift_insert_pastes_then_restores(self):
        self.assertEqual(self.run_paste(("terminal", "shift_insert", "echo hi")), "placed")
        self.si.assert_called_once_with()
        self.assertEqual(self.clip.text, "OLD")

    def test_secure_types_and_never_touches_clipboard(self):
        self.assertEqual(self.run_paste(("secure", "type", "s3cret")), "placed")
        self.ttype.assert_called_once_with("s3cret")
        self.assertEqual(self.clip.writes, [])

    def test_secure_failure_is_failed(self):
        self.assertEqual(self.run_paste(("secure", "type", "s3cret"), inject=False), "failed")
        self.assertEqual(self.clip.writes, [])

    def test_secure_handoff_never_copies(self):
        # مسار دفاعي (insert_target مبيرجّعوش): حتى لو جه، الحافظة متتلمسش
        self.assertEqual(self.run_paste(("secure", "handoff", "s3cret")), "handoff")
        self.assertEqual(self.clip.writes, [])

    def test_handoff_neither_injects_nor_copies(self):
        self.assertEqual(self.run_paste(("gui", "handoff", "hello")), "handoff")
        self.ttype.assert_not_called()
        self.cv.assert_not_called()
        self.assertEqual(self.clip.writes, [])

    def test_auto_paste_off_copies_owned_without_inject(self):
        # الكتابة التلقائية مقفولة = المستخدم عايز النص على الحافظة يلزقه بنفسه
        self.assertEqual(self.run_paste(("gui", "type", "hello"), auto_paste=False), "handoff")
        self.assertEqual(self.clip.text, "hello")
        self.ttype.assert_not_called()
        core.mark_clip_owned.assert_called_once_with(2)

    def test_auto_paste_off_copy_failure_is_clip_failed(self):
        self.clip.fail_copy = True
        self.assertEqual(self.run_paste(("gui", "type", "hello"), auto_paste=False), "clip_failed")

    def test_auto_paste_off_secure_never_copies(self):
        self.assertEqual(self.run_paste(("secure", "type", "s3cret"), auto_paste=False), "handoff")
        self.assertEqual(self.clip.writes, [])

    def test_missing_target_classifies_on_the_spot(self):
        # العقد القديم (target مش محطوط): التصنيف بيحصل جوه paste_text نفسه
        for p in self.clip.patches() + [mock.patch.object(core.time, "sleep"),
                                        mock.patch.object(core, "CFG", {"auto_paste": True})]:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("winput.focused_info",
                        return_value={"is_password": False, "class": "TermControl",
                                      "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.paste_shift_insert", return_value=True) as si:
            self.assertEqual(core.paste_text("echo hi"), "placed")
        si.assert_called_once_with()

    def test_guard_false_hands_off_without_typing_or_copying(self):
        # M6: الهدف اتغيّر → منحقنش ومننسخش؛ الواجهة بتعرض النص بزرار نسخ
        self.assertEqual(self.run_paste(("gui", "type", "hello"), guard=lambda: False), "handoff")
        self.ttype.assert_not_called()
        self.assertEqual(self.clip.writes, [])

    def test_guard_false_on_paste_path_restores_clipboard(self):
        self.assertEqual(self.run_paste(("gui", "ctrl_v", "hello"), guard=lambda: False),
                         "handoff")
        self.cv.assert_not_called()
        self.assertEqual(self.clip.text, "OLD")

    def test_guard_false_secure_never_types(self):
        self.assertEqual(self.run_paste(("secure", "type", "s3cret"), guard=lambda: False),
                         "handoff")
        self.ttype.assert_not_called()


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

    # زي chains.FeatureClient: مين فرّغ (محلي؟) وهل المعالجة ردّت
    stt_local = False
    ai_ok = True

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
            "dictionary": [], "insert_method": "auto",
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
        app.client = lambda *a, **k: fake
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
        app.client = lambda *a, **k: fake
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
        # الكتابة حرف حرف من غير نسخة احتياطية على الحافظة
        self.assertEqual(log, ["history_add", "on_text", "type", "recording_save"])
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_secure_with_auto_paste_off_skips_typing_and_copy(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
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
        self.assertNotIn("done", [s for s, _ in app.events],
                         "مفيش «done» — مفيش حاجة اتكتبت ولا اتسلمت")

    def test_secure_type_failure_reports_err(self):
        # الخانة الآمنة: الدقات فشلت → "err" (اكتبها بنفسك) من غير "done" ومن غير عرض النص
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
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
        self.assertEqual(app.events[-1], ("err", "مقدرتش أكتب في خانة الباسورد — اكتبها بنفسك"))

    def test_gui_type_failure_shows_unplaced(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
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

    def test_clip_failed_routes_to_err_not_unplaced(self):
        # مفيش حقن ولا نسخة على الحافظة → رسالة خطأ، مش toast "انسخه بنفسك"
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": False, "class": "Edit",
                                          "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="clip_failed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.unplaced, [])
        self.assertIn(("err", "مقدرتش أكتب النص ولا أنسخه — جرّب تاني"), app.events)

    def test_multiline_terminal_is_handoff(self):
        # متعدد لحد الترمنال: toast بزرار نسخ، ومفيش حقن ولا نسخ (R1 #4)
        app = make_app()
        fake = FakeClient(text="سطر\nسطر")
        app.client = lambda *a, **k: fake
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
        self.assertEqual(log, ["history_add", "on_text", "recording_save"])
        self.assertFalse(ttype.called)
        self.assertFalse(si.called)
        self.assertEqual(app.unplaced, [out])


if __name__ == "__main__":
    unittest.main()


class TestGuardRunsRightBeforeInjection(unittest.TestCase):
    def test_guard_checked_after_clipboard_preparation(self):
        # الترتيب: نسخ للحافظة الأول، الفحص بعده، والحقن آخر حاجة
        order = []
        clip = _Clipboard()
        clip.copy = lambda t: order.append("copy") or clip.write(t)
        patches = clip.patches() + [mock.patch.object(core.time, "sleep"),
                                    mock.patch.object(core, "CFG", {"auto_paste": True})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("winput.paste_ctrl_v", side_effect=lambda: order.append("inject") or True):
            r = core.paste_text("نص", ("gui", "ctrl_v", "نص"),
                                guard=lambda: order.append("guard") or True)
        self.assertEqual(r, "placed")
        # (بعدهم نسخة رجوع الحافظة القديمة — اختبارها في TestPasteText)
        self.assertEqual(order[:3], ["copy", "guard", "inject"])
