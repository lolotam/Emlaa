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
import wave
import tempfile
import dataclasses
import threading
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core  # noqa: E402


# ترقيعات على مستوى الموديول (الاختبار اللي محتاج قيمة تانية بيرقّع فوقها): الاختبارات
# عمرها ما تلمس الصوت ولا UI Automation الحقيقيين — begin()/cancel() بيصفّروا بـ
# winsound.Beep، وعلى جهاز CI من غير كارت صوت ومن غير ديسكتوب حقيقي النداءات دي ممكن
# تعلّق الـrun كله. واللوج بيروح لملف مؤقت مش emlaa-error.log الحقيقي.
_module_patches = []


def setUpModule():
    tmp = tempfile.mkdtemp(prefix="emlaa_unit_process_")
    # begin()/end() بيشغّلوا ثريدات بروب الباسورد اللي بتنادي winput.focused_info —
    # من غير الترقيعة دي كانت بتنادي UI Automation الحقيقي على ديسكتوب الـCI
    import winput
    for p in (mock.patch.object(core, "beep"),
              mock.patch.object(core, "ERR_LOG", os.path.join(tmp, "emlaa-error.log")),
              mock.patch.object(core, "_foreground_app", return_value=""),
              # التسجيل الفاشل بيتحفظ — في مجلد مؤقت، مش ملفات المستخدم
              mock.patch.object(core, "HISTORY_PATH", os.path.join(tmp, "history.json")),
              mock.patch.object(core, "RECORDINGS_DIR", os.path.join(tmp, "recordings")),
              mock.patch.object(winput, "focused_info",
                                return_value={"is_password": False, "class": "Edit", "editable": True})):
        p.start()
        _module_patches.append(p)


def tearDownModule():
    while _module_patches:
        _module_patches.pop().stop()


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


class BlockingEnsureRec:
    """ريكوردر وهمي: ensure_open بيستنى على Event — بيحاكي ريكونكت الميك البطيء
    (F1) عشان نحاكي المستخدم اللي وقّف/لغى والنص ده."""

    def __init__(self):
        self.started = 0
        self.discarded = 0
        self.entered = threading.Event()
        self.gate = threading.Event()

    def ensure_open(self):
        self.entered.set()
        self.gate.wait(5)
        return True

    def start(self):
        self.started += 1

    def stop(self):
        return "WAV"

    def discard(self):
        self.discarded += 1

    def close(self):
        pass


class FailingEnsureRec:
    """ريكوردر وهمي: أول ensure_open بيسدّ وبيرجّع False (ميك فاشل)، والباقي
    بيرجّع True فورًا — عشان نحاكي «أول begin فشل والقفل اتساب في النص،
    والمستخدم لغى وبدأ عملية جديدة». """

    def __init__(self):
        self.started = 0
        self.discarded = 0
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.calls = 0

    def ensure_open(self):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            self.gate.wait(5)
            return False
        return True

    def start(self):
        self.started += 1

    def stop(self):
        return "WAV"

    def discard(self):
        self.discarded += 1

    def close(self):
        pass


class FakeClient:
    """مزوّد وهمي: بيرجّع نصوص ثابتة وسجل بكل نداء."""

    # زي chains.FeatureClient: مين فرّغ (محلي؟) وهل المعالجة ردّت
    stt_local = False
    ai_ok = True

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

    def test_begin_cancel_new_begin_while_failing_ensure_open(self):
        # H2: أول begin بيسدّ في ensure_open (هيرجّع False) — المستخدم لغى وبدأ
        # عملية جديدة. لما الأول يرجع ممن يمسح الدولة ولا ينشر خطأ الميك فوق الجديد.
        rec = FailingEnsureRec()
        app = make_app(rec=rec)
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            t = threading.Thread(target=app.begin, args=("normal",))
            t.start()
            self.assertTrue(rec.entered.wait(5), "ensure_open ما بدأش يستنى")
            app.cancel()                          # يلغي الأول ويشيل _op
            self.assertFalse(app.recording)
            app.begin("prompt")                   # عملية جديدة تملك الحالة
            self.assertTrue(app.recording)
            self.assertEqual(app._op.mode, "prompt")
            rec.gate.set()                        # خلّي أول ensure_open يرجع False
            t.join(10)
            self.assertFalse(t.is_alive())
        self.assertEqual(rec.started, 1, "الالتقاط بدأ مرة واحدة (للجديدة)")
        self.assertTrue(app.recording)
        self.assertEqual(app._op.mode, "prompt")
        self.assertNotIn(("err", "الميكروفون مش متاح — وصّله وجرّب، أو غيّره من الإعدادات"), app.events)

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
        app.client = lambda *a, **k: fake
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

    def test_cancel_discard_runs_inside_state_lock(self):
        # K4: الديسكارد لازم يقع جوّه القفل — لو سبق التسجيل الجديد، الديسكارد
        # المتأخر كان هيمسحه. الستوب بيسجّل حالة القفل وقت الديسكارد.
        app = make_app()
        seen = []
        rec = app.rec
        real_discard = rec.discard

        def discard():
            seen.append((app._state_lock.locked(), rec.started))
            real_discard()

        rec.discard = discard
        with mock.patch.object(core, "beep"):
            app.begin("normal")
            app.cancel()
        self.assertEqual(rec.discarded, 1)
        self.assertEqual(seen, [(True, 1)], "الديسكارد اتندى برّه القفل أو شاف جيل غلط")

    def test_cancel_when_idle_is_noop(self):
        app = make_app()
        with mock.patch.object(core, "beep"):
            app.cancel()
        self.assertFalse(app.recording)
        self.assertIsNone(app._op)
        self.assertEqual(app.rec.discarded, 0)

    def test_begin_cancelled_while_ensure_open_blocks_does_not_start(self):
        # F1: ensure_open بيسدّ (ريكونكت)، والمستخدم بيلغي في النص — لما يرجّع
        # begin لازم يشوف إن الدورة اتلغت ومايبدأش تسجيل يتيم (rec.start).
        rec = BlockingEnsureRec()
        app = make_app(rec=rec)
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            t = threading.Thread(target=app.begin, args=("normal",))
            t.start()
            self.assertTrue(rec.entered.wait(5), "ensure_open ما بدأش يستنى")
            app.cancel()                       # بيقفل recording ويشيل _op
            self.assertFalse(app.recording)
            rec.gate.set()                     # خلّي ensure_open يرجع
            t.join(10)
            self.assertFalse(t.is_alive())
        self.assertEqual(rec.started, 0, "rec.start اتندى رغم إن التسجيل اتلغى")
        self.assertFalse(app.recording)

    def test_begin_order_beep_then_start_then_rec(self):
        # الترتيب المطلوب: الصفارة برّه القفل، بعدها الالتقاط، وبعدين إعلان "rec"
        app = make_app()
        order = []
        app.rec.start = mock.Mock(side_effect=lambda: order.append("start"))
        app.on_state = lambda st, msg=None: order.append("state:" + st)
        with mock.patch.object(core, "beep", side_effect=lambda *a: order.append("beep")), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
        self.assertEqual(order, ["beep", "start", "state:rec"])

    def test_begin_cancel_during_beep_never_starts_and_not_rec(self):
        # المستخدم ألغى جوّه الصفارة: الالتقاط ممن يبدأ، وآخر حالة مش "rec"
        app = make_app()

        def beep_cancel(freq, dur):
            app.cancel()

        with mock.patch.object(core, "beep", side_effect=beep_cancel), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
        self.assertEqual(app.rec.started, 0, "rec.start اتندى رغم الإلغاء في الصفارة")
        self.assertNotEqual(app.events[-1][0], "rec")


class TestProcess(unittest.TestCase):
    def test_process_reads_mode_from_operation(self):
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(fake.calls, [("transcribe", None), ("prompt",)])
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
        app.client = lambda *a, **k: fake
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
        with mock.patch.object(core, "log_error"), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertFalse(app.busy)

    def test_process_empty_transcript_clears_busy(self):
        # أي early return جوّه process لازم يفكّ الحجز (user ممكن يسجّل تاني)
        app = make_app()
        app.client = lambda *a, **k: FakeClient(text="")
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertFalse(app.busy)
        self.assertEqual(app.texts, [])
        # التفريغ الفاضي بقى «فشل»: الصوت اتحفظ في السجل عشان التفريغ اليدوي
        self.assertIn(("err", "مطلعش نص — قرّب من الميك وجرّب تاني"), app.events)

    def test_process_normal_mode_success(self):
        # «مرحبا بالعالم» كلمة منها مش في قايمة التخطّي (العالم) → polish عادي
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)])
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
        app.client = lambda *a, **k: fake
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


class TestProcessDoneState(unittest.TestCase):
    """H1: «done» بيتنشر بس لما النتيجة انكتبت أو اتسلّمت — مش فوق «clip_failed»
    ولا فشل كتابة خانة الباسورد الآمنة."""

    def test_clip_failed_last_state_is_err(self):
        # «clip_failed» ناشر "err" فوق — مينفعش يتغطى بـ"done" بعده
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="clip_failed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.events[-1][0], "err")
        self.assertFalse(app.busy)

    def test_secure_failed_reports_err_and_no_unplaced(self):
        # خانة آمنة فشل كتابتها: "err" من غير "done" ومن غير on_unplaced
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit", "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="failed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.events[-1], ("err", "مقدرتش أكتب في خانة الباسورد — اكتبها بنفسك"))
        self.assertEqual(app.unplaced, [])
        hist.assert_not_called()
        self.assertFalse(app.busy)

    def test_placed_publishes_done(self):
        # الكتابة نجحت → «done» زي ما هي
        app = make_app()
        fake = FakeClient()
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.events[-1], ("done", "normal"))

    def test_secure_auto_paste_off_publishes_err(self):
        # L2: خانة آمنة + auto_paste مقفول = مفيش كتابة ولا نسخ — لازم رسالة
        # خطأ بدل ما الواجهة تفضل واقفة على "work".
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        cfg = dict(core.DEFAULTS)
        cfg["auto_paste"] = False
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", cfg), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text") as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(app.events[-1],
                         ("err", "الكتابة التلقائية مقفولة — خانة الباسورد مينفعش أنسخ لها"))
        paste.assert_not_called()
        hist.assert_not_called()
        rsave.assert_not_called()
        self.assertFalse(app.busy)


def _cfg(**over):
    """إعدادات وهمية لوحدات F2 — عشان الاختبار ميعتمدش على config.json الحقيقي."""
    base = {"polish": True, "bypass_short": True, "bypass_max_words": 3,
            "dictionary": [], "history_keep_last10": True}
    base.update(over)
    return base


class TestBypassProcess(unittest.TestCase):
    def test_short_reply_skips_llm_entirely(self):
        # رد يومي قصير: مفيش أي نداء chat — المخرج هو الكلمة نفسها
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertIsNone(fake.last_chat, "مفيش chat = مفيش موديل شات شغل")
        self.assertEqual(app.texts, ["تمام"])
        paste.assert_called_once_with("تمام", ("gui", "type", "تمام"))
        self.assertEqual(hist.call_args.kwargs.get("bypass"), True)
        self.assertFalse(app.busy)

    def test_short_reply_trailing_period_cleaned_locally(self):
        app = make_app()
        fake = FakeClient(text="تمام.")
        app.client = lambda *a, **k: fake
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
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)])
        self.assertEqual(app.texts, ["p:تمام شكرا يا رب"])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_bypass_disabled_by_config(self):
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg(bypass_short=False)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_prompt_mode_unaffected_by_bypass(self):
        # فرع البرومبت ماشي على الـLLM حتى لو النص قصير من القايمة
        app = make_app()
        fake = FakeClient(text="تمام")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", _cfg()), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True):
            app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(fake.calls, [("transcribe", None), ("prompt",)])
        self.assertEqual(app.texts, ["P:تمام"])
        self.assertEqual(hist.call_args.kwargs.get("bypass"), False)

    def test_translate_mode_unaffected_by_bypass(self):
        app = make_app()
        fake = FakeClient(text="Yes please")
        app.client = lambda *a, **k: fake
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


class TestSecurePrivacy(unittest.TestCase):
    """F2 (خصوصية): خانة باسورد عمرها ما توصل للموديل في الوضع العادي."""

    def test_secure_focus_skips_polish_and_pastes_raw(self):
        # الباسورد بيتكتب زي ما اتفرّغ — مفيش polish ولا fix_mixed، والتصنيف
        # بييجي من نفس معلومات الفوكس (مفيش نداء focused_info تاني).
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit",
                                         "editable": True}), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111) as hist, \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value=True) as paste:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None)],
                         "الباسورد ممن يوصل polish/light_clean")
        self.assertEqual(app.texts, [])
        paste.assert_called_once_with("s3cret!", ("secure", "type", "s3cret!"))
        hist.assert_not_called()
        self.assertFalse(app.busy)

    def test_late_password_after_gui_goes_secure_path(self):
        # الفوكس كان عادي وقت الاستعلام المبكّر (الموديل اشتغل)، واتحوّل لباسورد
        # قبل التصنيف → النتيجة بتتعامل آمنة: مفيش سجل/عرض/حافظة/صوت، كتابة بس
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        log = []
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=[
                    {"is_password": False, "class": "Edit", "editable": True},
                    {"is_password": True, "class": "Edit", "editable": True}]), \
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
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)],
                         "الموديل اشتغل لأن الاستعلام المبكّر شافه خانة عادية")
        self.assertEqual(log, ["type"], "النتيجة اتعاملت آمنة بعد الاستعلام الأخير")
        self.assertEqual(app.texts, [])
        self.assertEqual(app.unplaced, [])
        self.assertFalse(app.busy)

    def test_late_no_text_field_after_gui_is_handoff(self):
        # الفوكس اتساب لمكان من غير خانة كتابة قبل التصنيف → handoff مش كتابة
        app = make_app()
        fake = FakeClient(text="نص")
        app.client = lambda *a, **k: fake
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=[
                    {"is_password": False, "class": "Edit", "editable": True},
                    {"is_password": False, "class": "", "editable": False}]), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=111), \
                mock.patch.object(core, "recording_save"), \
                mock.patch("pyperclip.copy"), \
                mock.patch("winput.type_text") as ttype, \
                mock.patch.object(core.time, "sleep"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertFalse(ttype.called, "editable=False لازم handoff مش كتابة")
        self.assertEqual(app.unplaced, ["p:نص"])

    def test_early_password_then_gui_refuses_insert(self):
        # K3: الفوكس كان على باسورد وقت التسجيل وبعدين اتنقل لخانة عادية —
        # ممن نكتب كلمة السر في أي مكان، والموديل عمره ما اشتغل.
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=[
                    {"is_password": True, "class": "Edit", "editable": True},
                    {"is_password": False, "class": "Edit", "editable": True}]), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text") as paste, \
                mock.patch("pyperclip.copy") as clip:
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(fake.calls, [("transcribe", None)], "مفيش polish للباسورد")
        hist.assert_not_called()
        rsave.assert_not_called()
        paste.assert_not_called()
        clip.assert_not_called()
        self.assertEqual(app.texts, [])
        self.assertEqual(app.unplaced, [])
        self.assertEqual(app.events[-1],
                         ("err", "الفوكس اتنقل من خانة الباسورد — مكتبتش حاجة"))

    def _run_secure(self, mode, early, late, text="s3cret!"):
        app = make_app()
        fake = FakeClient(text=text)
        app.client = lambda *a, **k: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=[early, late]), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode=mode))
        return app, fake, hist, rsave, paste

    def test_early_password_blocks_model_in_prompt_mode(self):
        app, fake, hist, rsave, paste = self._run_secure(
            "prompt",
            {"is_password": True, "class": "Edit", "editable": True},
            {"is_password": True, "class": "Edit", "editable": True})
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertNotIn(("prompt",), fake.calls)
        hist.assert_not_called()
        rsave.assert_not_called()
        self.assertEqual(app.texts, [])
        paste.assert_called_once_with("s3cret!", ("secure", "type", "s3cret!"))

    def test_early_password_blocks_model_in_translate_mode(self):
        app, fake, hist, rsave, paste = self._run_secure(
            "translate",
            {"is_password": True, "class": "Edit", "editable": True},
            {"is_password": True, "class": "Edit", "editable": True})
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertNotIn(("translate",), fake.calls)
        hist.assert_not_called()
        rsave.assert_not_called()
        self.assertEqual(app.texts, [])
        paste.assert_called_once_with("s3cret!", ("secure", "type", "s3cret!"))

    def test_early_password_blocks_model_in_normal_mode(self):
        app, fake, hist, rsave, paste = self._run_secure(
            "normal",
            {"is_password": True, "class": "Edit", "editable": True},
            {"is_password": True, "class": "Edit", "editable": True})
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertFalse(any(c[0] == "polish" for c in fake.calls))
        hist.assert_not_called()
        rsave.assert_not_called()
        self.assertEqual(app.texts, [])
        paste.assert_called_once_with("s3cret!", ("secure", "type", "s3cret!"))

    def test_early_password_late_password_no_clipboard_copy(self):
        # الإدراج الآمن كتابة بس — من غير حافظة. نتأكد إن مسار paste_text الحقيقي
        # ما بيلمسش الحافظة (type بس) ولا سجل ولا صوت.
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        log = []
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=[
                    {"is_password": True, "class": "Edit", "editable": True},
                    {"is_password": True, "class": "Edit", "editable": True}]), \
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
        self.assertEqual(log, ["type"], "الإدراج الآمن كتابة بس — من غير حافظة/سجل/صوت")
        self.assertEqual(app.texts, [])
        self.assertEqual(app.unplaced, [])

    def test_early_focus_capture_happens_before_transcribe(self):
        # K1: قراية الفوكس المبكّرة لازم تحصل قبل cl.transcribe — عشان نمسك حالة
        # الخانة والوقت اللي التسجيل لسه واقف عليها.
        app = make_app()
        fake = FakeClient(text="مرحبا")
        order = []
        fake.transcribe = lambda wav, lang: order.append("transcribe") or "مرحبا"
        app.client = lambda *a, **k: fake
        app.busy = True

        def focused():
            order.append("focused")
            return GUI_FOCUS

        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", side_effect=focused), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add"), \
                mock.patch.object(core, "recording_save"), \
                mock.patch.object(core, "paste_text", return_value="placed"):
            app.process("WAV", core.Operation(mode="normal"))
        self.assertEqual(order, ["focused", "transcribe", "focused"])


class TestProbePrivacy(unittest.TestCase):
    """L1 (خصوصية): حالة «باسورد؟» بتتقرا من لحظة التسجيل (begin/end) على ثريد
    دايمون — ومبتخفّضش أبدًا طول عمر العملية."""

    def test_probe_begin_password_refuses_when_focus_moved(self):
        # probe["begin"]=True (باسورد وقت التسجيل) وبعدين الفوكس كله عادي —
        # مفيش موديل ولا سجل ولا حافظة ولا صوت، ورفض بخطأ الحركة.
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        op = core.Operation(mode="normal")
        op.probe["begin"] = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text") as paste:
            app.process("WAV", op)
        self.assertEqual(fake.calls, [("transcribe", None)], "مفيش polish للباسورد")
        hist.assert_not_called()
        rsave.assert_not_called()
        paste.assert_not_called()
        self.assertEqual(app.texts, [])
        self.assertEqual(app.events[-1],
                         ("err", "الفوكس اتنقل من خانة الباسورد — مكتبتش حاجة"))

    def test_probe_end_password_refuses_when_focus_moved(self):
        # probe["end"]=True (باسورد لحظة الإيقاف) وبعدين الفوكس عادي — نفس الرفض.
        app = make_app()
        fake = FakeClient(text="s3cret!")
        app.client = lambda *a, **k: fake
        app.busy = True
        op = core.Operation(mode="normal")
        op.probe["end"] = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add") as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text") as paste:
            app.process("WAV", op)
        self.assertEqual(fake.calls, [("transcribe", None)])
        hist.assert_not_called()
        rsave.assert_not_called()
        paste.assert_not_called()
        self.assertEqual(app.events[-1],
                         ("err", "الفوكس اتنقل من خانة الباسورد — مكتبتش حاجة"))

    def test_begin_probe_runs_off_calling_thread(self):
        # قراية «باسورد؟» في begin() لازم تحصل على ثريد دايمون مش على ثريد
        # اللي نادى begin — UI Automation بيقدر يسدّ والـlistener لازم يفضل سريع.
        app = make_app()
        caller = threading.get_ident()
        seen = []
        done = threading.Event()

        def focused():
            seen.append(threading.get_ident())
            done.set()
            return GUI_FOCUS

        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.focused_info", side_effect=focused):
            app.begin("normal")
        self.assertTrue(done.wait(1), "ثريد البروب ما قراش الفوكس")
        self.assertEqual(len(seen), 1, "قراية الفوكس حصلت أكتر من مرة")
        self.assertNotEqual(seen[0], caller, "البروب اشتغل على ثريد اللي نادى begin")


class TestHistoryBypassFlag(unittest.TestCase):
    def test_bypass_key_stored_only_when_true(self):
        # التسجيل القديم (من غير bypass) يفضل زي ما هو، والجديد بس ياخد المفتاح
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "history.json")
            with mock.patch.object(core, "HISTORY_PATH", p), \
                    mock.patch.object(core, "RECORDINGS_DIR", os.path.join(d, "recordings")), \
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


class TestContextStyles(unittest.TestCase):
    """F5: الأسلوب بيتحدد من البرنامج، واسم البرنامج نفسه مبيوصلش للموديل."""

    def test_process_passes_builtin_profile_for_target_app(self):
        app = make_app()
        fake = FakeClient(text="الكود ده فيه مشكلة في الـ API")
        app.client = lambda *a, **k: fake
        # CFG صريح: قايمة المعالجة الافتراضية (مش ملف ومفاتيح الجهاز اللي بيشغّل الاختبار)
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
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

    # زي chains.FeatureClient: مين فرّغ (محلي؟) وهل المعالجة ردّت
    stt_local = False
    ai_ok = True

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
        app.client = lambda *a, **k: fake
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
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)])
        self.assertEqual(app.texts, [MIXED_FIXED])
        paste.assert_called_once_with(MIXED_FIXED, ("gui", "type", MIXED_FIXED))

    def test_raw_mode_stays_byte_identical(self):
        # الوضع الخام: المخرج = التفريغ حرفي — من غير أي تصحيح
        app, fake, _ = self._run(cfg={"polish": False, "dictionary": []})
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_dev_profile_skips_fix(self):
        # تطبيق dev: الكود يفضل شكلي التقني — polish شغل بالبروفايل من غير تصحيح
        app, fake, _ = self._run(target_app="code")
        self.assertIn(("polish", "dev"), fake.calls)
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_context_styles_off_still_skips_fix_for_dev(self):
        # H4: حتى لو context_styles مقفول، تطبيق dev لسه بياخد استثناء بايت-بايت
        cfg = dict(core.DEFAULTS)
        cfg["context_styles"] = False
        app, fake, _ = self._run(target_app="code", cfg=cfg)
        self.assertEqual(fake.calls, [("transcribe", None), ("polish", None)])
        self.assertEqual(app.texts, [MIXED_RAW])

    def test_terminal_target_skips_fix(self):
        # ترمنال: النص ممكن يكون أمر — بايتاته ما تتغيّرش، والاستراتيجية shift_insert
        app, fake, paste = self._run(focus=TERM_FOCUS)
        self.assertEqual(app.texts, [MIXED_RAW])
        paste.assert_called_once_with(MIXED_RAW, ("terminal", "shift_insert", MIXED_RAW))

    def test_prompt_mode_untouched(self):
        # البرومبت مبيروح fix_mixed خالص — الموديل هو اللي بيشكّله
        app, fake, _ = self._run(mode="prompt")
        self.assertEqual(fake.calls, [("transcribe", None), ("prompt",)])
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
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertEqual(app.texts, ["تمام، شكرا"])


class TestRecordingSaveTmpCleanup(unittest.TestCase):
    """G5: ملف .mp3.tmp لازم يتمسح لو الكتابة أو os.replace فشل، والـprune بينضّف الزيادة."""

    def _fake_lameenc(self):
        fake = mock.MagicMock()
        fake.Encoder.return_value.encode.return_value = b"mp3"
        fake.Encoder.return_value.flush.return_value = b""
        return fake

    def test_replace_failure_removes_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            wav = os.path.join(d, "in.wav")
            with wave.open(wav, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 1600)
            recs = os.path.join(d, "recs")
            with mock.patch.dict(sys.modules, {"lameenc": self._fake_lameenc()}), \
                    mock.patch.object(core, "RECORDINGS_DIR", recs), \
                    mock.patch.object(core, "HISTORY_PATH", os.path.join(d, "history.json")), \
                    mock.patch.object(core, "log_error"), \
                    mock.patch("os.replace", side_effect=RuntimeError("boom")):
                core.recording_save(123, wav)
            leftovers = [n for n in os.listdir(recs) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [], "الـ.tmp لسه موجود بعد فشل الـreplace")

    def test_prune_deletes_stray_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            recs = os.path.join(d, "recs")
            os.makedirs(recs)
            stray = os.path.join(recs, "999.mp3.tmp")
            with open(stray, "wb") as f:
                f.write(b"leftover")
            old = time.time() - 700          # بقايا قديمة — الحديثة ممكن تكون كتابة لسه شغّالة
            os.utime(stray, (old, old))
            with mock.patch.object(core, "RECORDINGS_DIR", recs), \
                    mock.patch.object(core, "HISTORY_PATH", os.path.join(d, "history.json")), \
                    mock.patch.object(core, "log_error"):
                core.recordings_prune()
            self.assertFalse(os.path.exists(stray))


class TestFeatureWiring(unittest.TestCase):
    """كل وضع بيمشي على عميل ميزته (FeatureClient)، والخام، ورسالة فشل المعالجة، والكاش."""

    def run_process(self, mode="normal", fake=None, cfg=None, focus=GUI_FOCUS):
        app = make_app()
        fake = fake or FakeClient(text="الكلام ده جملة طويلة شوية.")
        seen = []
        app.client = lambda m="normal": seen.append(m) or fake
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", cfg or dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=dict(focus)), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "_copy_to_clipboard") as clip, \
                mock.patch.object(core, "paste_text", return_value="placed") as paste:
            app.process("WAV", core.Operation(mode=mode))
        return app, fake, seen, hist, rsave, clip, paste

    def test_each_mode_uses_its_client(self):
        for mode in ("normal", "prompt", "translate"):
            _, _, seen, *_ = self.run_process(mode)
            self.assertEqual(seen, [mode])

    def test_empty_ai_list_is_fully_raw(self):
        # «Yes.» كانت هتبقى «Yes» من light_clean — قايمة المعالجة الفاضية = خام بالكامل
        cfg = dict(core.DEFAULTS)
        cfg["features"] = json.loads(json.dumps(core.DEFAULTS["features"]))
        cfg["features"]["normal"]["ai"] = []
        app, fake, _, hist, _, _, paste = self.run_process(fake=FakeClient(text="Yes."), cfg=cfg)
        self.assertEqual(fake.calls, [("transcribe", None)])
        self.assertEqual(paste.call_args.args[0], "Yes.")

    def test_prompt_and_translate_without_ai_items_type_raw_text_and_call_no_model(self):
        for mode in ("prompt", "translate"):
            with self.subTest(mode=mode):
                cfg = dict(core.DEFAULTS)
                cfg["features"] = json.loads(json.dumps(core.DEFAULTS["features"]))
                cfg["features"][mode]["ai"] = []
                app, fake, _, _, _, _, paste = self.run_process(mode, fake=FakeClient(text="عايز صفحة"), cfg=cfg)
                self.assertEqual(fake.calls, [("transcribe", None)])
                self.assertEqual(paste.call_args.args[0], "عايز صفحة")
                self.assertEqual(app.events[-1], ("done", core.NO_AI_MSG))

    def test_edit_without_ai_items_refuses_before_recording(self):
        app = make_app()
        cfg = dict(core.DEFAULTS)
        cfg["features"] = json.loads(json.dumps(core.DEFAULTS["features"]))
        cfg["features"]["edit"]["ai"] = []
        with mock.patch.object(core, "CFG", cfg), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("edit")
        self.assertFalse(app.recording)
        self.assertEqual(app.events[-1], ("err", core.EDIT_NO_AI_MSG))

    def test_prompt_ai_failure_reports_it(self):
        fake = FakeClient(text="عايز صفحة هبوط")
        fake.ai_ok = False
        fake.to_prompt = lambda t: t
        app, *_ = self.run_process("prompt", fake=fake)
        self.assertEqual(app.events[-1], ("done", "مقدرتش أحوّله — اتكتب الكلام زي ما اتقال"))

    def test_password_transcript_never_reaches_ai_history_or_clipboard(self):
        secure = {"is_password": True, "class": "Edit", "editable": True}
        for mode in ("normal", "prompt", "translate"):
            app, fake, _, hist, rsave, clip, paste = self.run_process(mode, focus=secure)
            self.assertEqual(fake.calls, [("transcribe", None)], mode)
            hist.assert_not_called()
            rsave.assert_not_called()
            clip.assert_not_called()
            self.assertEqual(app.unplaced, [])
            self.assertEqual(paste.call_args.args[1][0], "secure")


class TestClientCache(unittest.TestCase):
    def test_rebuilt_when_keys_change_for_the_same_provider(self):
        app = make_app()
        with mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("providers.read_key_pools", return_value={"groq": ["a"]}):
            first = app.client("normal")
            self.assertIs(app.client("normal"), first)
        with mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("providers.read_key_pools", return_value={"groq": ["a", "b"]}):
            self.assertIsNot(app.client("normal"), first)

    def test_one_client_per_mode(self):
        app = make_app()
        with mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("providers.read_key_pools", return_value={"groq": ["a"]}):
            self.assertIsNot(app.client("normal"), app.client("prompt"))


class TestHotkeyRestartDeferred(unittest.TestCase):
    def test_restart_waits_until_operation_ends(self):
        app = make_app()
        app.start_hotkey = mock.Mock()
        app.busy = True
        app.restart_hotkey()
        app.start_hotkey.assert_not_called()
        app.busy = False
        app._apply_pending_hotkeys()
        app.start_hotkey.assert_called_once()

    def test_mic_failure_at_begin_applies_pending_restart(self):
        app = make_app()
        app.start_hotkey = mock.Mock()

        def mic_fails_while_settings_are_saved():
            app.restart_hotkey()                 # الإعدادات اتحفظت وهو بيحاول يفتح الميك
            return False

        app.rec = mock.Mock(ensure_open=mock.Mock(side_effect=mic_fails_while_settings_are_saved))
        with mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "_probe_password"):
            app.begin("normal")
        self.assertFalse(app.recording)
        app.start_hotkey.assert_called_once()

    def test_too_short_recording_applies_pending_restart(self):
        app = make_app()
        app.start_hotkey = mock.Mock()
        app.rec = mock.Mock(stop=mock.Mock(return_value=None))      # مفيش صوت كفاية
        with app._state_lock:
            app.recording = True
        app.restart_hotkey()
        app.start_hotkey.assert_not_called()
        with mock.patch.object(core, "beep"):
            app.end()
        app.start_hotkey.assert_called_once()

    def test_process_applies_pending_restart_on_exit(self):
        app = make_app()
        app.start_hotkey = mock.Mock()
        app.client = lambda m="normal": FakeClient(text="")
        app.busy = True
        app.restart_hotkey()
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.focused_info", return_value=dict(GUI_FOCUS)), \
                mock.patch.object(core, "_foreground_app", return_value=""):
            app.process("WAV", core.Operation(mode="normal"))
        app.start_hotkey.assert_called_once()


if __name__ == "__main__":
    unittest.main()

