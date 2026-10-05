# -*- coding: utf-8 -*-
"""
اختبارات وضع التعديل في المكان (F6) — Client.edit و دورة التعديل في core.
مفيش شبكة ولا مفاتيح: طبقة HTTP (OpenAI و Gemini) متزوّدة stub، والريكوردر
والـwinput كله fake — بنختبر القرار الفعلي مش الاستدعاءات.
"""
import os
import sys
import time
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core        # noqa: E402
import providers   # noqa: E402


def _wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ── stubs لطبقة HTTP ───────────────────────────────────────────────────────────
def _oa_stub(content=None, exc=None):
    """OpenAI client وهمي: content = نص الرد (None = فاضي)، exc = خطأ يتداس."""
    r = mock.Mock()
    r.choices = [mock.Mock()]
    r.choices[0].message.content = content
    oa = mock.Mock()
    oa.with_options.return_value = oa
    if exc:
        oa.chat.completions.create.side_effect = exc
    else:
        oa.chat.completions.create.return_value = r
    return oa


def _gemini_body(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _make_edit_client(pid="groq"):
    return providers.Client(pid, "test-key")


# ── stubs لدورة التسجيل ───────────────────────────────────────────────────────
class StubRec:
    def __init__(self):
        self.started = 0
        self.ensure_ok = True

    def ensure_open(self):
        return self.ensure_ok

    def start(self):
        self.started += 1

    def stop(self):
        return "WAV"

    def discard(self):
        pass

    def close(self):
        pass


def make_app():
    app = core.App.__new__(core.App)
    app.rec = StubRec()
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


class FakeEditClient:
    """مزوّد وهمي: transcribe بيرجّع التعليمات، edit بيرجّع النتيجة (أو None)."""

    def __init__(self, instruction="حط عنوان", result="النص المعدل"):
        self.instruction = instruction
        self.result = result
        self.calls = []
        self.vocab = []
        self.vocab_extra = []
        self.last_chat = None

    def engine(self):
        return {"stt": "fake", "stt_model": "m1"}

    def transcribe(self, wav, lang):
        self.calls.append(("transcribe", lang))
        return self.instruction

    def edit(self, selection, instruction):
        self.calls.append(("edit", selection, instruction))
        self.last_chat = ("fake", "m1")
        return self.result


GUI_FOCUS = {"is_password": False, "class": "Edit", "editable": True}


# ── Client.edit عبر طبقة HTTP حقيقية (مزوّدة stub) ────────────────────────────
class TestClientEdit(unittest.TestCase):
    """edit بيرجّع النص المعدّل بس، أو None على أي فشل/فاضي/صدى — مبيرجعش المدخل أبدًا."""

    def test_openai_normal_text(self):
        cl = _make_edit_client("groq")
        with mock.patch.object(cl, "_openai", return_value=_oa_stub("النص المعدل")), \
                mock.patch.object(core, "log_error"):
            self.assertEqual(cl.edit("نص محدد", "حوّله لعنوان"), "النص المعدل")

    def test_openai_fenced_or_labelled_reply_is_cleaned(self):
        # نفس تنضيف الردود العادية: ``` ولافتة «النص المعدّل:» متتلزقش في مكان التحديد
        cl = _make_edit_client("groq")
        with mock.patch.object(cl, "_openai", return_value=_oa_stub("```\nالنص المعدل\n```")), \
                mock.patch.object(core, "log_error"):
            self.assertEqual(cl.edit("نص محدد", "ظبطه"), "النص المعدل")

    def test_openai_empty_returns_none(self):
        cl = _make_edit_client("groq")
        with mock.patch.object(cl, "_openai", return_value=_oa_stub("")), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_openai_think_only_returns_none(self):
        cl = _make_edit_client("groq")
        with mock.patch.object(cl, "_openai", return_value=_oa_stub("<think>بفكر…</think>")), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_openai_echo_of_input_returns_none(self):
        # الموديل رجّع شكل المدخل نفسه (لسه فيه <<<) → مرفوض
        cl = _make_edit_client("groq")
        echo = "<<<النص>>>\nنص محدد\n<<<التعليمات>>>\nظبطه"
        with mock.patch.object(cl, "_openai", return_value=_oa_stub(echo)), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_openai_exception_returns_none(self):
        cl = _make_edit_client("groq")
        with mock.patch.object(cl, "_openai", return_value=_oa_stub(exc=RuntimeError("boom"))), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_gemini_normal_text(self):
        cl = _make_edit_client("gemini")
        with mock.patch.object(providers, "_post_json", return_value=_gemini_body("النص المعدل")), \
                mock.patch.object(core, "log_error"):
            self.assertEqual(cl.edit("نص محدد", "حوّله لعنوان"), "النص المعدل")

    def test_gemini_empty_returns_none(self):
        cl = _make_edit_client("gemini")
        with mock.patch.object(providers, "_post_json", return_value=_gemini_body("")), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_gemini_think_only_returns_none(self):
        cl = _make_edit_client("gemini")
        with mock.patch.object(providers, "_post_json",
                               return_value=_gemini_body("<think>بفكر…</think>")), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_gemini_exception_returns_none(self):
        cl = _make_edit_client("gemini")
        with mock.patch.object(providers, "_post_json", side_effect=RuntimeError("boom")), \
                mock.patch.object(core, "log_error"):
            self.assertIsNone(cl.edit("نص محدد", "ظبطه"))

    def test_prompt_builds_delimited_input(self):
        # النص والتعليمات بيتفصلوا بعلامات، والـsystem هو EDIT_SYSTEM نفسه
        cl = _make_edit_client("groq")
        oa = _oa_stub("النص المعدل")
        with mock.patch.object(cl, "_openai", return_value=oa), \
                mock.patch.object(core, "log_error"):
            cl.edit("نص محدد", "حوّله لعنوان")
        kw = oa.chat.completions.create.call_args.kwargs
        self.assertEqual(kw["temperature"], 0.2)
        self.assertEqual(kw["messages"][0]["content"], providers.EDIT_SYSTEM)
        self.assertIn("<<<النص>>>\nنص محدد\n<<<التعليمات>>>\nحوّله لعنوان", kw["messages"][1]["content"])


# ── دورة التعديل في core ──────────────────────────────────────────────────────
class TestProcessEdit(unittest.TestCase):
    def _run(self, op, fake=None, same=True, paste="placed"):
        app = make_app()
        fake = fake or FakeEditClient()
        app.client = lambda: fake
        app.busy = True
        with mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)), \
                mock.patch("winput.same_target", return_value=same), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch.object(core, "history_add", return_value=7) as hist, \
                mock.patch.object(core, "recording_save") as rsave, \
                mock.patch.object(core, "paste_text", return_value=paste) as paste_fn, \
                mock.patch.object(core, "_copy_to_clipboard", return_value=True) as clip:
            app.process("WAV", op)
        return app, fake, hist, rsave, paste_fn, clip

    def test_success_pastes_and_records_without_selection(self):
        op = core.Operation(mode="edit", selection="نص محدد أصلي")
        app, fake, hist, rsave, paste_fn, _ = self._run(op)
        # النتيجة اتحقنت
        paste_fn.assert_called_once()
        self.assertEqual(paste_fn.call_args[0][0], "النص المعدل")
        # السجل: mode="edit"، raw=التعليمات، result=النتيجة — النص المحدد مش متخزّن
        self.assertEqual(hist.call_args[0][:3], ("edit", "حط عنوان", "النص المعدل"))
        self.assertNotIn("نص محدد أصلي", hist.call_args[0])
        rsave.assert_called_once_with(7, "WAV")
        self.assertEqual(app.events[-1], ("done", "edit"))
        self.assertFalse(app.busy)

    def test_edit_none_pastes_nothing_and_err(self):
        app, fake, hist, rsave, paste_fn, _ = self._run(
            core.Operation(mode="edit", selection="نص"), fake=FakeEditClient(result=None))
        self.assertFalse(paste_fn.called, "مفيش لزق لما التعديل يفشل")
        hist.assert_not_called()
        rsave.assert_not_called()
        self.assertEqual(app.events[-1], ("err", "معرفتش أعدّل النص — جرّب تاني"))
        self.assertFalse(app.busy)

    def test_same_target_false_does_not_type_and_unplaces(self):
        app, fake, hist, rsave, paste_fn, clip = self._run(
            core.Operation(mode="edit", selection="نص"), same=False)
        self.assertFalse(paste_fn.called, "الهدف اتغيّر = مفيش حقن")
        clip.assert_called_once_with("النص المعدل")
        self.assertEqual(app.unplaced, ["النص المعدل"])
        hist.assert_called_once()
        rsave.assert_called_once()
        self.assertEqual(app.events[-1], ("done", "edit"))
        self.assertFalse(app.busy)


# ── بداية التعديل: أسر التحديد والرفض ──────────────────────────────────────────
class TestBeginEdit(unittest.TestCase):
    def test_empty_selection_never_starts_recorder(self):
        app = make_app()
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.capture_target",
                           return_value={"hwnd": 1, "runtime_id": (1,),
                                         "class": "Edit", "selection": "",
                                         "selection_hash": ""}):
            app.begin("edit")
            self.assertTrue(_wait_until(lambda: not app.recording, 3))
        self.assertEqual(app.rec.started, 0, "التحديد فاضي = مفيش تسجيل")
        self.assertIsNone(app._op)
        self.assertIn(("err", "حدّد النص اللي عايز تعدّله الأول"), app.events)

    def test_password_field_refused_model_never_called(self):
        app = make_app()
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.capture_target",
                           return_value={"hwnd": 1, "runtime_id": (1,),
                                         "class": "Edit", "selection": "نص محدد",
                                         "selection_hash": "abc"}) as capture, \
                mock.patch("winput.focused_info",
                           return_value={"is_password": True, "class": "Edit", "editable": True}):
            app.begin("edit")
            self.assertTrue(_wait_until(lambda: not app.recording, 3))
        self.assertEqual(app.rec.started, 0)
        self.assertIn(("err", "مينفعش تعديل خانة باسورد"), app.events)
        # الرفض قبل أي قراية للتحديد — ولا UIA ولا Ctrl+C على خانة باسورد
        capture.assert_not_called()

    def test_capture_budget_exceeded_begin_returns_fast(self):
        app = make_app()

        def slow_capture():
            time.sleep(3)
            return {"hwnd": 1, "runtime_id": (1,), "class": "Edit",
                    "selection": "نص", "selection_hash": "abc"}

        t0 = time.time()
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.capture_target", side_effect=slow_capture):
            app.begin("edit")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.2, "begin لازم يرجع فورًا من غير ما يستنى الأسر")
        self.assertTrue(_wait_until(lambda: not app.recording, 3))
        self.assertEqual(app.rec.started, 0)
        self.assertIn(("err", "حدّد النص اللي عايز تعدّله الأول"), app.events)

    def test_success_starts_recorder_with_captured_target(self):
        app = make_app()
        with mock.patch.object(core, "beep"), \
                mock.patch.object(core, "log_error"), \
                mock.patch.object(core, "_foreground_app", return_value=""), \
                mock.patch("winput.capture_target",
                           return_value={"hwnd": 7, "runtime_id": (3,), "class": "Edit",
                                         "selection": "نص محدد", "selection_hash": "abc"}), \
                mock.patch("winput.focused_info", return_value=GUI_FOCUS):
            app.begin("edit")
            self.assertTrue(_wait_until(lambda: app.rec.started > 0, 3))
        self.assertTrue(app.recording)
        self.assertEqual(app.rec.started, 1)
        self.assertEqual(app._op.mode, "edit")
        self.assertEqual(app._op.selection, "نص محدد")
        self.assertEqual(app._op.hwnd, 7)
        self.assertIn(("rec", "edit"), app.events)


# ── winput.same_target ─────────────────────────────────────────────────────────
class TestSameTarget(unittest.TestCase):
    def _op(self):
        return core.Operation(mode="edit", hwnd=7, runtime_id=(3,),
                              selection="نص", selection_hash="abc")

    def test_match(self):
        import winput
        with mock.patch.object(winput, "foreground_hwnd", return_value=7), \
                mock.patch.object(winput, "_focused_element", return_value=object()), \
                mock.patch.object(winput, "_runtime_id", return_value=(3,)), \
                mock.patch.object(winput, "_selection_text", return_value="نص"), \
                mock.patch.object(winput, "_selection_hash", return_value="abc"):
            self.assertTrue(winput.same_target(self._op()))

    def test_hwnd_mismatch(self):
        import winput
        with mock.patch.object(winput, "foreground_hwnd", return_value=8):
            self.assertFalse(winput.same_target(self._op()))

    def test_runtime_id_mismatch(self):
        import winput
        with mock.patch.object(winput, "foreground_hwnd", return_value=7), \
                mock.patch.object(winput, "_focused_element", return_value=object()), \
                mock.patch.object(winput, "_runtime_id", return_value=(99,)):
            self.assertFalse(winput.same_target(self._op()))

    def test_selection_changed(self):
        import winput
        with mock.patch.object(winput, "foreground_hwnd", return_value=7), \
                mock.patch.object(winput, "_focused_element", return_value=object()), \
                mock.patch.object(winput, "_runtime_id", return_value=(3,)), \
                mock.patch.object(winput, "_selection_text", return_value="نص تاني"), \
                mock.patch.object(winput, "_selection_hash", return_value="xyz"):
            self.assertFalse(winput.same_target(self._op()))


# ── الإعدادات: رفض الزرار المكرر ──────────────────────────────────────────────
class TestSaveSettingsHotkey(unittest.TestCase):
    def test_duplicate_hotkey_rejected(self):
        import app_web
        ctrl = mock.Mock()
        api = app_web.Api(ctrl)
        cfg = dict(core.DEFAULTS)
        with mock.patch.object(core, "CFG", cfg), \
                mock.patch.object(providers, "read_keys", return_value={"groq": "k"}), \
                mock.patch.object(core, "save_config"):
            r = api.save_settings({"hotkey_normal": "ctrl_r", "hotkey_prompt": "ctrl_r"})
        self.assertFalse(r["ok"])
        self.assertIn("err", r)

    def test_edit_hotkey_can_be_off_without_conflict(self):
        import app_web
        ctrl = mock.Mock()
        ctrl.hotkeys = []
        ctrl.engine = None
        api = app_web.Api(ctrl)
        cfg = dict(core.DEFAULTS)
        with mock.patch.object(core, "CFG", cfg), \
                mock.patch.object(providers, "read_keys", return_value={"groq": "k"}), \
                mock.patch.object(core, "save_config"):
            r = api.save_settings({"hotkey_edit": ""})
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()
