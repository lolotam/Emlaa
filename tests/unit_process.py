# -*- coding: utf-8 -*-
"""
اختبارات دورة التسجيل في core.py — Operation والانتقالات الذّرية بين
(recording, busy). مفيش ميكروفون ولا شبكة ولا مفاتيح: الـrecorder والمزوّد
وكل النداءات الخارجية stubs.
"""
import os
import sys
import json
import time
import tempfile
import dataclasses
import threading
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core  # noqa: E402


class StubRec:
    """ميكروفون وهمي: بيسجّل كل دعوة عشان الاختبار يتأكد مين بدأ ومين وقف."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.discarded = 0
        self.ensure_ok = True
        self.stop_result = "WAV"
        self.stop_exc = None

    def ensure_open(self):
        return self.ensure_ok

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1
        if self.stop_exc:
            raise self.stop_exc
        return self.stop_result

    def discard(self):
        self.discarded += 1

    def close(self):
        pass


class FakeClient:
    """مزوّد وهمي: بيرجّع نصوص ثابتة وسجل بكل نداء."""

    def __init__(self, text="مرحبا بالعالم"):
        self.vocab = []
        self.text = text
        self.calls = []
        # زي Client الحقيقي: transcribe بيرمّيه None، والـchat بيسجل مين شغل
        self.last_chat = None

    def engine(self):
        e = {"stt": "fake", "stt_model": "m1"}
        if self.last_chat:
            e["chat"], e["chat_model"] = self.last_chat
        return e

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


# F3: معلومات فوكس ثابتة للاختبارات — الهدف عادي (مش باسورد) من غير ما نعتمد
# على النافذة المركّزة فعلياً وقت تشغيل الاختبار
GUI_FOCUS = {"is_password": False, "class": "Edit", "editable": True}


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


class TestOperation(unittest.TestCase):
    def test_defaults(self):
        op = core.Operation(mode="normal")
        self.assertEqual(op.mode, "normal")
        self.assertEqual(op.target_app, "")
        self.assertEqual(op.target_class, "")
        self.assertEqual(op.hwnd, 0)
        self.assertEqual(op.runtime_id, ())
        self.assertEqual(op.selection, "")
        self.assertEqual(op.selection_hash, "")

    def test_frozen(self):
        # العملية ثابتة بعد ما تتولد — أي تعديل بعد كده = سباق ما بنريدهوش
        op = core.Operation(mode="normal")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            op.mode = "prompt"


class TestBeginEnd(unittest.TestCase):
    def test_begin_reserves_state_and_operation(self):
        app = make_app()
        with mock.patch.object(core, "_foreground_app", return_value="Chrome"):
            app.begin("prompt")
        self.assertTrue(app.recording)
        self.assertFalse(app.busy)
        self.assertEqual(app.active_mode, "prompt")
        self.assertIsInstance(app._op, core.Operation)
        self.assertEqual(app._op.mode, "prompt")
        # F5: اسم البرنامج بيتحفظ على العملية (منصّفاً وصغير) — حقول الهدف
        # التانية لسه فاضية ومهام تالية هتملّيها
        self.assertEqual(app._op.target_app, "chrome")
        self.assertEqual(app._op.hwnd, 0)
        self.assertEqual(app._op.runtime_id, ())
        self.assertEqual(app.rec.started, 1)
        self.assertIn(("rec", "prompt"), app.events)

    def test_begin_refused_when_recording(self):
        app = make_app()
        with mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
            app.begin("prompt")
        self.assertEqual(app.rec.started, 1)
        self.assertEqual(app._op.mode, "normal")
        self.assertEqual(app.active_mode, "normal")

    def test_begin_refused_when_busy(self):
        # التفريغ شغّال = مفيش تسجيل جديد حتى لو recording مقفول
        app = make_app()
        app.busy = True
        with mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
        self.assertFalse(app.recording)
        self.assertEqual(app.rec.started, 0)
        self.assertIsNone(app._op)

    def test_begin_mic_failure_rolls_back_reservation(self):
        app = make_app()
        app.rec.ensure_ok = False
        with mock.patch.object(core, "beep"), mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
        self.assertFalse(app.recording)
        self.assertFalse(app.busy)
        self.assertIsNone(app._op)
        self.assertEqual(app.rec.started, 0)
        self.assertIn(("err", "الميكروفون مش متاح — وصّله وجرّب، أو غيّره من الإعدادات"), app.events)

    def test_begin_captures_foreground_app_case_insensitive(self):
        # F5: الاسم بيتنصّف ويصغّر عشان يطابق overrides الإعدادات
        app = make_app()
        with mock.patch.object(core, "_foreground_app", return_value="  VSCode "):
            app.begin("normal")
        self.assertEqual(app._op.target_app, "vscode")

    def test_concurrent_begin_exactly_one_per_round(self):
        # اللي كان بيحصل: اتنين ثيردين بيروحوا begin في نفس اللحظة —
        # كل واحد بيلاقي recording=False وكلاهما بيبدأ. دلوقتي النسخ الأول بس بيحجز.
        app = make_app()
        beep = mock.patch.object(core, "beep")   # من غيره الاختبار بيطلّع 100 صفارة حقيقية
        beep.start()
        self.addCleanup(beep.stop)
        fg = mock.patch.object(core, "_foreground_app", return_value="")
        fg.start()
        self.addCleanup(fg.stop)
        for round_no in range(100):
            barrier = threading.Barrier(2)
            errs = []

            def worker():
                try:
                    barrier.wait(5)
                    app.begin("normal")
                except BaseException as e:
                    errs.append(e)

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start(); t2.start()
            t1.join(10); t2.join(10)
            self.assertFalse(errs, errs)
            self.assertFalse(t1.is_alive() or t2.is_alive())
            self.assertEqual(app.rec.started, round_no + 1,
                             f"الدورة {round_no}: بدأت أكتر من عملية واحدة")
            self.assertTrue(app.recording)
            app.cancel()
            self.assertFalse(app.recording)
            self.assertFalse(app.busy)
        self.assertEqual(app.rec.discarded, 100)

    def test_begin_refused_while_end_stop_is_blocked(self):
        # stop() ماسك بين Event: الفجوة من end() لحد ما الـworker يبدأ
        # بتنفتح قدامنا — والتسجيل الجديد لازم يترفض فيها.
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        gate = threading.Event()
        in_stop = threading.Event()
        rec = app.rec
        real_stop = rec.stop

        def blocking_stop():
            in_stop.set()
            gate.wait(5)
            return real_stop()

        rec.stop = blocking_stop
        with mock.patch.object(core, "beep"), mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.begin("normal")
            t = threading.Thread(target=app.end)
            t.start()
            self.assertTrue(in_stop.wait(5), "stop() ماستنشاش")
            # جوّه الفجوة: التسجيل قفل والتفريغ اتحجز
            self.assertFalse(app.recording)
            self.assertTrue(app.busy)
            app.begin("prompt")
            self.assertEqual(app.rec.started, 1, "تسجيل جديد بدأ فوق التفريغ الشغّال")
            self.assertFalse(app.recording)
            self.assertTrue(app.busy)
            gate.set()
            t.join(10)
            self.assertFalse(t.is_alive())
            deadline = time.time() + 5
            while app.busy and time.time() < deadline:
                time.sleep(0.01)
            self.assertFalse(app.busy, "worker خلّى بس busy لسه محجوز")

    def test_end_stop_failure_clears_busy(self):
        app = make_app()
        app.rec.stop_exc = RuntimeError("الميك اتقطع")
        with mock.patch.object(core, "beep"), mock.patch.object(core, "log_error") as log, \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
            app.end()
        self.assertFalse(app.recording)
        self.assertFalse(app.busy, "قفل التسجيل بدون worker = لازم busy يتترجّع")
        self.assertEqual(app.rec.stopped, 1)
        self.assertIn(("err", "مشكلة في قراية الصوت — جرّب تاني"), app.events)
        self.assertTrue(log.called)

    def test_end_short_recording_clears_busy(self):
        app = make_app()
        app.rec.stop_result = None
        with mock.patch.object(core, "beep"), mock.patch.object(core, "log_error"):
            app.begin("normal")
            app.end()
        self.assertFalse(app.recording)
        self.assertFalse(app.busy)
        self.assertIn(("ready", "التسجيل كان قصير أوي — اتكلم شوية وبعدين وقّف"), app.events)

    def test_end_passes_operation_to_process(self):
        # الـworker لازم ياخد الـOperation نفسه — مش الوضع من متغير بيتغيّر
        app = make_app()
        got = []
        ran = threading.Event()

        def fake_process(wav, op):
            got.append((wav, op))
            ran.set()
            app._set_busy(False)

        app.process = fake_process
        app.rec.stop_result = "MYWAV"
        with mock.patch.object(core, "beep"), mock.patch.object(core, "log_error"):
            app.begin("translate")
            op = app._op
            app.end()
        self.assertTrue(ran.wait(5))
        self.assertEqual(got, [("MYWAV", op)])
        self.assertIs(got[0][1], op)
        self.assertEqual(op.mode, "translate")
        self.assertFalse(app.recording)
        self.assertIsNone(app._op)

    def test_cancel_drops_operation(self):
        app = make_app()
        app.begin("normal")
        app.cancel()
        self.assertFalse(app.recording)
        self.assertIsNone(app._op)
        self.assertEqual(app.rec.discarded, 1)
        # وإلغاء بعده يبدأ دورة جديدة من غير ما النسخ الأول تتمسك في حاجة
        with mock.patch.object(core, "beep"):
            app.begin("prompt")
        self.assertTrue(app.recording)
        self.assertEqual(app._op.mode, "prompt")

    def test_cancel_when_idle_is_noop(self):
        app = make_app()
        with mock.patch.object(core, "beep"):
            app.cancel()
        self.assertFalse(app.recording)
        self.assertIsNone(app._op)
        self.assertEqual(app.rec.discarded, 0)


class TestProcess(unittest.TestCase):
    def test_process_reads_mode_from_operation(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("prompt",)])
        self.assertEqual(app.texts, ["P:مرحبا بالعالم"])
        paste.assert_called_once_with("P:مرحبا بالعالم", ("gui", "type", "P:مرحبا بالعالم"))
        hist.assert_called_once_with("prompt", "مرحبا بالعالم", "P:مرحبا بالعالم",
                                     None, engine={"stt": "fake", "stt_model": "m1",
                                                   "chat": "fake", "chat_model": "m1"},
                                     bypass=False, app="")
        rsave.assert_called_once_with(111, "WAV")
        self.assertEqual(app.events[-1], ("done", "prompt"))
        self.assertFalse(app.busy, "الـfinally المفروض يفكّ الحجز بعد العملية")

    def test_process_translate_mode_uses_no_language(self):
        # وضع الترجمة: التفريغ بيطلّع عربي أو إنجليزي — مش مجبر على العربي
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="translate"))
        self.assertEqual(fake.calls[0], ("transcribe", None))
        self.assertEqual(fake.calls[1], ("translate",))
        self.assertEqual(app.texts, ["T:مرحبا بالعالم"])
        self.assertFalse(app.busy)

    def test_process_ui_callback_error_still_clears_busy(self):
        # لو on_state("work") رمى خطأ، busy لو فضل محجوز البرنامج كان هيقفل لحد ما يتقفل
        app = make_app()
        app.busy = True
        app.on_state = mock.Mock(side_effect=[RuntimeError("ui gone"), None])
        with mock.patch.object(core, "log_error"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertFalse(app.busy)

    def test_process_empty_transcript_clears_busy(self):
        # أي early return جوّه process لازم يفكّ الحجز (user ممكن يسجّل تاني)
        app = make_app()
        app.client = lambda: FakeClient(text="")
        app.busy = True
        with mock.patch.object(core, "log_error"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertFalse(app.busy)
        self.assertEqual(app.texts, [])
        self.assertIn(("ready", "مطلعش نص — قرّب من الميك وجرّب تاني"), app.events)

    def test_process_normal_mode_success(self):
        # «مرحبا بالعالم» كلمة منها مش في قايمة التخطّي (العالم) → polish عادي
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("polish", None)])
        hist.assert_called_once()
        self.assertEqual(hist.call_args[0][0], "normal")
        rsave.assert_called_once_with(7, "WAV")
        self.assertEqual(app.texts, ["p:مرحبا بالعالم"])
        paste.assert_called_once_with("p:مرحبا بالعالم", ("gui", "type", "p:مرحبا بالعالم"))
        self.assertEqual(app.events[-1], ("done", "normal"))
        self.assertFalse(app.busy)
        self.assertFalse(app.recording)

    def test_process_unpasted_text_reports_unplaced(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="failed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.unplaced, ["p:مرحبا بالعالم"])
        self.assertFalse(app.busy)


def _cfg(**over):
    """إعدادات وهمية لوحدات F2 — عشان الاختبار ميعتمدش على config.json الحقيقي."""
    base = {"polish": True, "bypass_short": True, "bypass_max_words": 3,
            "language": "ar", "dictionary": [], "history_keep_last10": True}
    base.update(over)
    return base


class TestBypassProcess(unittest.TestCase):
    def test_short_reply_skips_llm_entirely(self):
        # رد يومي قصير: مفيش أي نداء chat — المخرج هو الكلمة نفسها
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", "ar")])
        self.assertIsNone(fake.last_chat, "مفيش chat = مفيش موديل شات شغل")
        self.assertEqual(app.texts, ["تمام"])
        paste.assert_called_once_with("تمام", ("gui", "type", "تمام"))
        self.assertEqual(hist.call_args.kwargs.get("bypass"), True)
        self.assertFalse(app.busy)

    def test_short_reply_trailing_period_cleaned_locally(self):
        app = make_app()
        fake = FakeClient(text="تمام.")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.texts, ["تمام"])
        paste.assert_called_once_with("تمام", ("gui", "type", "تمام"))

    def test_longer_text_still_polished(self):
        # 4 كلمات = فوق الحد 3 → الـLLM زي ما هي
        app = make_app()
        fake = FakeClient(text="تمام شكرا يا رب")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("polish", None)])
        self.assertEqual(app.texts, ["p:تمام شكرا يا رب"])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_bypass_disabled_by_config(self):
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg(bypass_short=False)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("polish", None)])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_prompt_mode_unaffected_by_bypass(self):
        # فرع البرومبت ماشي على الـLLM حتى لو النص قصير من القايمة
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("prompt",)])
        self.assertEqual(app.texts, ["P:تمام"])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_translate_mode_unaffected_by_bypass(self):
        app = make_app()
        fake = FakeClient(text="Yes please")
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="translate"))
        self.assertEqual(fake.calls, [("transcribe", None), ("translate",)])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)


class TestHistoryBypassFlag(unittest.TestCase):
    def test_bypass_key_stored_only_when_true(self):
        # التسجيل القديم (من غير bypass) يفضل زي ما هو، والجديد بس ياخد المفتاح
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "history.json")
            with mock.patch.object(core, "HISTORY_PATH", p), \
                    mock.patch.object(core, "log_error"), \
                    mock.patch.object(core, "CFG", _cfg()):
                core.history_add("normal", "مرحبا بالعالم", "مرحبا بالعالم")
                core.history_add("normal", "تمام", "تمام", bypass=True)
            with open(p, encoding="utf-8") as f:
                items = json.load(f)
        self.assertEqual(len(items), 2)
        self.assertIs(items[0]["bypass"], True)          # الأحدث = اللي اتخطّت
        self.assertNotIn("bypass", items[1])             # القديم من غير المفتاح
        # السجل القديم بيتقرا من غير KeyError — الويتس مايتغيّرش بسبب المفتاح الجديد
        self.assertEqual(items[1]["result"], "مرحبا بالعالم")


if __name__ == "__main__":
    unittest.main()


class TestContextStyles(unittest.TestCase):
    """F5: الأسلوب بيتحدد من البرنامج، واسم البرنامج نفسه مبيوصلش للموديل."""

    def test_process_passes_builtin_profile_for_target_app(self):
        app = make_app()
        fake = FakeClient(text="الكود ده فيه مشكلة في الـ API")
        app.client = lambda: fake
        with mock.patch.object(core, "log_error"), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=None) as hist, \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="normal", target_app="code"))
        self.assertIn(("polish", "dev"), fake.calls)
        self.assertEqual(hist.call_args.kwargs["app"], "code")

    def test_polish_appends_rule_after_base_prompt_and_never_sends_exe(self):
        import providers
        cl = providers.Client("groq", "test-key")
        sent = {}
        cl._chat = lambda system, text, temperature=0.2: sent.update(system=system) or text
        cl.polish("نص قصير", profile="dev")
        system = sent["system"]
        self.assertIn(providers.POLISH_SYSTEM, system)
        self.assertGreater(system.index(providers.STYLE_RULES["dev"]), system.index(providers.POLISH_SYSTEM))
        for leak in ("code.exe", "WindowsTerminal", "Visual Studio Code"):
            self.assertNotIn(leak, system)

    def test_polish_without_profile_is_unchanged(self):
        import providers
        cl = providers.Client("groq", "test-key")
        sent = {}
        cl._chat = lambda system, text, temperature=0.2: sent.update(system=system) or text
        cl.polish("نص قصير")
        self.assertEqual(sent["system"], providers.POLISH_SYSTEM)


# ── F7: تصحيح النص المختلط في دورة التسجيل ───────────────────────────────────

MIXED_RAW = "اعمل push للbranch, وبعدين افتح PR?"
MIXED_FIXED = "اعمل push للـ branch، وبعدين افتح PR؟"
TERM_FOCUS = {"is_password": False, "class": "TermControl", "editable": True}


class FakeIdentityClient:
    """مزوّد وهمي الهوية: polish/prompt/translate بيرجّع النص زي ما هو —
    فأي تعديل في المخرج لازم يكون من fix_mixed مش من الموديل."""

    def __init__(self, text=MIXED_RAW):
        self.text = text
        self.vocab = []
        self.calls = []
        self.last_chat = None

    def engine(self):
        return {"stt": "fake", "stt_model": "m1"}

    def transcribe(self, wav, lang):
        self.calls.append(("transcribe", lang))
        return self.text

    def polish(self, t, profile=None):
        self.calls.append(("polish", profile))
        self.last_chat = ("fake", "m1")
        return t

    def to_prompt(self, t):
        self.calls.append(("prompt",))
        self.last_chat = ("fake", "m1")
        return t

    def translate(self, t):
        self.calls.append(("translate",))
        self.last_chat = ("fake", "m1")
        return t


class TestFixMixedProcess(unittest.TestCase):
    """F7: التصحيح في الوضع العادي بس (polish أو تخطّي الرد القصير)،
    غير التطبيقات dev والـterminal — الخام بايت-بايت، والبرومبت/الترجمة ملهاش دعوة."""

    def _run(self, mode="normal", text=MIXED_RAW, focus=GUI_FOCUS, target_app="", cfg=None):
        app = make_app()
        fake = FakeIdentityClient(text)
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", cfg or dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=focus), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode=mode, target_app=target_app))
        return app, fake, paste

    def test_normal_mode_gets_fixed(self):
        # الطريق العادي: بعد polish المخرج بيتصلّح ويُحقن كده
        app, fake, paste = self._run()
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("polish", None)])
        self.assertEqual(app.texts, [MIXED_FIXED])
        paste.assert_called_once_with(MIXED_FIXED, ("gui", "type", MIXED_FIXED))

    def test_raw_mode_stays_byte_identical(self):
        # الوضع الخام: المخرج = التفريغ حرفي — من غير أي تصحيح
        app, fake, _ = self._run(cfg={"polish": False, "language": "ar", "dictionary": []})
        self.assertEqual(fake.calls, [("transcribe", "ar")])
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_dev_profile_skips_fix(self):
        # تطبيق dev: الكود يفضل شكلي التقني — polish شغل بالبروفايل من غير تصحيح
        app, fake, _ = self._run(target_app="code")
        self.assertIn(("polish", "dev"), fake.calls)
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_terminal_target_skips_fix(self):
        # ترمنال: النص ممكن يكون أمر — بايتاته ما تتغيّرش، والاستراتيجية shift_insert
        app, fake, paste = self._run(focus=TERM_FOCUS)
        self.assertEqual(app.texts, [MIXED_RAW])
        paste.assert_called_once_with(MIXED_RAW, ("terminal", "shift_insert", MIXED_RAW))

    def test_prompt_mode_untouched(self):
        # البرومبت مبيروح fix_mixed خالص — الموديل هو اللي بيشكّله
        app, fake, _ = self._run(mode="prompt")
        self.assertEqual(fake.calls, [("transcribe", "ar"), ("prompt",)])
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_translate_mode_untouched(self):
        app, fake, _ = self._run(mode="translate")
        self.assertEqual(fake.calls, [("transcribe", None), ("translate",)])
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_secure_target_never_rewritten(self):
        # خانة باسورد: fix_mixed مبيتطبّقش (أي «,» بتتحول «،» بتغيّر الباسورد) —
        # بس سياسة الأسطر بتاعة التصنيف (أسطر → مسافات) لسه شغالة
        app, fake, paste = self._run(text="اعمل push,\nللbranch",
                                     focus={"is_password": True, "class": "", "editable": True})
        self.assertEqual(app.texts, [])
        paste.assert_called_once_with("اعمل push,\nللbranch",
                                      ("secure", "type", "اعمل push, للbranch"))

    def test_bypass_short_reply_also_fixed(self):
        # الرد القصير المتخطّي (light_clean) برضه مخرج وضع عادي
        app, fake, _ = self._run(text="تمام, شكرا")
        self.assertEqual(fake.calls, [("transcribe", "ar")])
        self.assertEqual(app.texts, ["تمام، شكرا"])

