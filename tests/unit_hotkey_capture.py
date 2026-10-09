# -*- coding: utf-8 -*-
"""
زراير التسجيل بأرقام ويندوز (vk) بدل أسماء pynput: نموذج الزرار والمطابقة الواحدة
(HotkeyMatcher) اللي المنع والتشغيل الاتنين بيستخدموها، وقرار المنع (HotkeyFilter)،
وتسجيل الزرار من الكيبورد (CaptureSession). كله منطق نقي — مفيش كيبورد حقيقي.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import smart  # noqa: E402

F7, F8, LCTRL, RCTRL, RALT, LSHIFT = 0x76, 0x77, 0xA2, 0xA3, 0xA5, 0xA0


class TestHotkeyModel(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(smart.hotkey_from_vks([F7]), smart.Hotkey(frozenset(), F7))
        self.assertEqual(smart.hotkey_from_vks([LCTRL, F7]), smart.Hotkey(frozenset({LCTRL}), F7))
        self.assertIsNone(smart.hotkey_from_vks([]))

    def test_shape_rules(self):
        self.assertTrue(smart.hotkey_shape_ok([]))
        self.assertTrue(smart.hotkey_shape_ok([RCTRL]))
        self.assertTrue(smart.hotkey_shape_ok([LCTRL, F7]))
        self.assertFalse(smart.hotkey_shape_ok([0x41, 0x42]))     # زرارين عاديين
        self.assertFalse(smart.hotkey_shape_ok([LCTRL, RALT]))    # موديفايرين
        self.assertFalse(smart.hotkey_shape_ok([F7, LCTRL]))      # الموديفاير لازم الأول
        self.assertFalse(smart.hotkey_shape_ok([0x1B]))           # Esc للإلغاء
        self.assertFalse(smart.hotkey_shape_ok([LCTRL, 0x1B]))
        self.assertFalse(smart.hotkey_shape_ok([1, 2, 3]))

    def test_labels(self):
        self.assertEqual(smart.hotkey_label([LCTRL, F7], "en"), "Left Ctrl + F7")
        self.assertEqual(smart.vk_label(RALT, "ar"), "Alt اليمين")
        self.assertEqual(smart.vk_label(0xB3, "en"), "Media Play/Pause")
        self.assertEqual(smart.vk_label(0x41, "ar"), "A")
        self.assertEqual(smart.vk_label(0xFE, "en"), "Key 0xFE")
        self.assertEqual(smart.hotkey_label([], "ar"), "")

    def test_legacy_names(self):
        self.assertEqual(smart.LEGACY_HOTKEY_VKS["alt_r"], RALT)
        self.assertEqual(smart.LEGACY_HOTKEY_VKS["f12"], 0x7B)


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.m = smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                      "prompt": smart.Hotkey(frozenset({LCTRL}), F7),
                                      "translate": smart.Hotkey(frozenset(), RCTRL)})

    def test_same_trigger_two_modes(self):
        self.assertEqual(self.m.match(F7, frozenset()), "normal")
        self.assertEqual(self.m.match(F7, frozenset({LCTRL})), "prompt")

    def test_extra_modifier_matches_nothing(self):
        self.assertIsNone(self.m.match(F7, frozenset({LSHIFT})))
        self.assertIsNone(self.m.match(F7, frozenset({LCTRL, LSHIFT})))

    def test_modifier_trigger_ignores_itself_in_held(self):
        self.assertEqual(self.m.match(RCTRL, frozenset({RCTRL})), "translate")

    def test_non_modifier_keys_in_held_are_ignored(self):
        # held بيتقارن بالموديفايرز بس — زرار عادي ماسك تاني مالوش دعوة بالمطابقة
        self.assertEqual(self.m.match(F7, frozenset({0x41})), "normal")

    def test_triggers(self):
        self.assertEqual(self.m.triggers(), {F7, RCTRL})


class TestFilter(unittest.TestCase):
    """قرار المنع: بيستخدم نفس المطابقة، ومتثبّت لكل دوسة حقيقية لحد ما الزرار يتساب."""

    def matcher(self):
        return smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                    "prompt": smart.Hotkey(frozenset({LCTRL}), F8),
                                    "translate": smart.Hotkey(frozenset(), RALT)})

    def make(self, initially_down=frozenset()):
        return smart.HotkeyFilter(self.matcher(), initially_down=initially_down)

    def test_single_trigger_suppressed_press_and_release(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        self.assertEqual(f.event(F7, False, False, False), (True, True))

    def test_unmatched_modifier_combination_is_not_suppressed(self):
        # F7 لوحده زرار التسجيل — Ctrl+F7 لسه بتاع البرنامج اللي قدامك
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F7, True, False, False), (True, False))

    def test_combo_release_suppressed_after_modifier_released_first(self):
        f = self.make()
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F8, True, False, False), (True, True))
        f.event(LCTRL, False, False, False)
        self.assertEqual(f.event(F8, False, False, False), (True, True))

    def test_bare_modifier_trigger_never_suppressed(self):
        self.assertEqual(self.make().event(RALT, True, False, False), (True, False))

    def test_injected_and_fake_ctrl_ignored(self):
        f = self.make()
        self.assertEqual(f.event(F7, True, True, False), (False, False))
        self.assertEqual(f.event(LCTRL, True, False, True), (False, False))
        self.assertEqual(f.held(), frozenset())

    def test_decision_latched_across_repeats(self):
        # Ctrl اتداس والـF7 ماسك: التكرار والتسيب بياخدوا قرار أول دوسة
        f = self.make()
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        f.event(LCTRL, True, False, False)
        self.assertEqual(f.event(F7, True, False, False), (True, True))
        self.assertEqual(f.event(F7, False, False, False), (True, True))

    def test_initially_held_ctrl_is_known(self):
        f = self.make(initially_down=frozenset({LCTRL}))
        self.assertEqual(f.event(F7, True, False, False), (True, False))   # Ctrl+F7، مش F7


class TestComboLogic(unittest.TestCase):
    def matcher(self):
        return smart.HotkeyMatcher({"normal": smart.Hotkey(frozenset(), F7),
                                    "prompt": smart.Hotkey(frozenset({LCTRL}), F7)})

    def test_toggle_same_trigger_two_modes(self):
        lg = smart.HotkeyLogic(self.matcher(), "toggle")
        lg.press(F7, 0.0, False, False, held=frozenset())
        self.assertEqual(lg.release(F7, 0.1, False, False), ["begin:normal"])
        lg.press(F7, 1.0, False, False, held=frozenset({LCTRL}))
        self.assertEqual(lg.release(F7, 1.1, False, False), ["begin:prompt"])

    def test_toggle_extra_modifier_does_nothing(self):
        lg = smart.HotkeyLogic(self.matcher(), "toggle")
        lg.press(F7, 0.0, False, False, held=frozenset({LSHIFT}))
        self.assertEqual(lg.release(F7, 0.1, False, False), [])

    def test_hold_extra_modifier_does_not_begin(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({LSHIFT})), [])

    def test_hold_combo_begin_end(self):
        lg = smart.HotkeyLogic(self.matcher(), "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False, held=frozenset({LCTRL})), ["begin:prompt"])
        self.assertEqual(lg.release(F7, 0.4, True, False), ["end"])

    def test_legacy_key_map_still_accepted(self):
        lg = smart.HotkeyLogic({F7: "normal"}, "hold")
        self.assertEqual(lg.press(F7, 0.0, False, False), ["begin:normal"])

    def test_alt_trigger_still_masked(self):
        lg = smart.HotkeyLogic(smart.HotkeyMatcher({"prompt": smart.Hotkey(frozenset(), RALT)}),
                               "toggle", alt_keys={RALT})
        self.assertEqual(lg.press(RALT, 0.0, False, False), ["mask"])


class TestCapture(unittest.TestCase):
    """تسجيل الزرار من الكيبورد: بيسجّل اللي اتداس جوّه الجلسة بس، وبيستنى التسيب."""

    def feed(self, s, events):
        return [s.event(vk, down, fake) for vk, down, fake in events]

    def test_altgr_records_right_alt_not_fake_ctrl(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(LCTRL, True, True), (RALT, True, False), (LCTRL, False, True), (RALT, False, False)])
        self.assertEqual((s.finished, s.result), (True, [RALT]))

    def test_single_key_ignores_auto_repeat(self):
        s = smart.CaptureSession(1)
        self.assertEqual(self.feed(s, [(F7, True, False), (F7, True, False)]), [True, True])
        self.assertFalse(s.decided)
        s.event(F7, False, False)
        self.assertEqual(s.result, [F7])

    def test_key_held_before_session_passes_through_including_repeats(self):
        s = smart.CaptureSession(1, initially_down=frozenset({LCTRL}))
        self.assertEqual(self.feed(s, [(LCTRL, True, False), (LCTRL, False, False)]), [False, False])
        self.assertFalse(s.decided)
        # بعد ما اتساب، دوسة جديدة عليه بتاعتنا
        self.assertTrue(s.event(LCTRL, True, False))

    def test_release_of_unknown_key_passes_through(self):
        s = smart.CaptureSession(1)
        self.assertEqual(self.feed(s, [(LCTRL, False, False)]), [False])

    def test_two_keys_finished_only_after_full_release(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(F7, True, False), (LCTRL, True, False), (F7, False, False)])
        self.assertTrue(s.decided)
        self.assertFalse(s.finished)
        self.assertTrue(s.event(LCTRL, False, False))     # لسه بتاعنا: متمنوع
        self.assertTrue(s.finished)
        self.assertEqual(s.result, [LCTRL, F7])

    def test_two_keys_needs_both_down_together(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(F7, True, False), (F7, False, False)])
        self.assertFalse(s.decided)

    def test_single_key_waits_for_other_captured_keys(self):
        s = smart.CaptureSession(1)
        self.feed(s, [(F7, True, False), (F8, True, False), (F7, False, False)])
        self.assertEqual((s.decided, s.finished, s.result), (True, False, [F7]))
        s.event(F8, False, False)
        self.assertTrue(s.finished)

    def test_two_non_modifiers_rejected(self):
        s = smart.CaptureSession(2)
        self.feed(s, [(0x41, True, False), (0x42, True, False), (0x41, False, False), (0x42, False, False)])
        self.assertTrue(s.finished)
        self.assertIsNone(s.result)
        self.assertIsNotNone(s.error)

    def test_escape_cancels_and_is_suppressed(self):
        s = smart.CaptureSession(1)
        self.assertTrue(s.event(0x1B, True, False))
        self.assertTrue(s.cancelled)
        self.assertTrue(s.decided)
        self.assertFalse(s.finished)              # Esc لسه ماتسابش
        self.assertTrue(s.event(0x1B, False, False))
        self.assertTrue(s.finished)
        self.assertIsNone(s.result)


class _ReplayListener:
    """Listener مزيّف: start() بيعدّي الأحداث على الفلتر بالترتيب ويسجّل اللي اتمنع."""

    class Suppressed(Exception):
        pass

    def __init__(self, events, filt):
        self.events, self.filt, self.suppressed, self.stopped = events, filt, [], False

    def suppress_event(self):
        raise self.Suppressed()

    def start(self):
        import types
        for vk, down, scan in self.events:
            data = types.SimpleNamespace(vkCode=vk, scanCode=scan, dwExtraInfo=0)
            try:
                self.filt(0x100 if down else 0x101, data)
            except self.Suppressed:
                self.suppressed.append((vk, down))

    def stop(self):
        self.stopped = True


class TestCaptureBridge(unittest.TestCase):
    def capture(self, count, events, held=(), timeout=10.0):
        import core
        from unittest import mock
        made = {}

        def factory(filt):
            made["l"] = _ReplayListener(events, filt)
            return made["l"]

        clock = {"t": 0.0}
        with mock.patch("winput.keys_down", return_value=frozenset(held)):
            r = core.capture_keys(count, timeout=timeout, listener_factory=factory,
                                  clock=lambda: clock["t"],
                                  sleep=lambda s: clock.__setitem__("t", clock["t"] + s))
        return r, made["l"]

    def test_single_key(self):
        r, lst = self.capture(1, [(F7, True, 0), (F7, False, 0)])
        self.assertEqual((r["ok"], r["keys"]), (True, [F7]))
        self.assertEqual(lst.suppressed, [(F7, True), (F7, False)])
        self.assertTrue(lst.stopped)

    def test_two_keys_after_full_release(self):
        r, _ = self.capture(2, [(F7, True, 0), (LCTRL, True, 0), (F7, False, 0), (LCTRL, False, 0)])
        self.assertEqual(r["keys"], [LCTRL, F7])
        self.assertIn("F7", r["label"])

    def test_pre_held_ctrl_passes_through(self):
        r, lst = self.capture(1, [(LCTRL, True, 0), (LCTRL, False, 0), (F7, True, 0), (F7, False, 0)],
                              held=(LCTRL,))
        self.assertEqual(r["keys"], [F7])
        self.assertNotIn((LCTRL, False), lst.suppressed)
        self.assertNotIn((LCTRL, True), lst.suppressed)

    def test_escape_cancels(self):
        r, _ = self.capture(1, [(0x1B, True, 0), (0x1B, False, 0)])
        self.assertEqual(r, {"ok": False, "err": "اتلغى"})

    def test_shape_error_reported(self):
        r, _ = self.capture(2, [(0x41, True, 0), (0x42, True, 0), (0x41, False, 0), (0x42, False, 0)])
        self.assertFalse(r["ok"])
        self.assertEqual(r["err"], smart.CAPTURE_PAIR_ERR)

    def test_timeout_waits_and_explains(self):
        r, lst = self.capture(1, [], timeout=0.2)
        self.assertFalse(r["ok"])
        self.assertIn("Fn", r["err"])
        self.assertTrue(lst.stopped)


class _Engine:
    def __init__(self, can_capture=True):
        self.can_capture = can_capture
        self.calls = []

    def try_begin_capture(self):
        self.calls.append("try")
        return self.can_capture

    def end_capture(self):
        self.calls.append("end")

    def pause_hotkey(self):
        self.calls.append("pause")

    def resume_hotkey(self):
        self.calls.append("resume")


class TestCaptureApi(unittest.TestCase):
    def api(self, engine):
        import app_web
        from unittest import mock
        ctrl = mock.Mock(engine=engine)
        return app_web.Api(ctrl)

    def test_result_echoes_feature_and_restores_engine(self):
        import core
        from unittest import mock
        eng = _Engine()
        with mock.patch.object(core, "capture_keys", return_value={"ok": True, "keys": [F7], "label": "F7"}):
            r = self.api(eng).capture_hotkey("translate", 1)
        self.assertEqual(r["feature"], "translate")
        self.assertEqual(eng.calls, ["try", "pause", "resume", "end"])

    def test_refused_while_recording(self):
        eng = _Engine(can_capture=False)
        r = self.api(eng).capture_hotkey("normal", 1)
        self.assertFalse(r["ok"])
        self.assertEqual(eng.calls, ["try"])

    def test_bad_request_refused(self):
        self.assertFalse(self.api(_Engine()).capture_hotkey("nope", 1)["ok"])
        self.assertFalse(self.api(_Engine()).capture_hotkey("normal", 3)["ok"])

    def test_second_capture_refused_while_one_runs(self):
        api = self.api(_Engine())
        api._capture_lock.acquire()
        try:
            self.assertFalse(api.capture_hotkey("normal", 1)["ok"])
        finally:
            api._capture_lock.release()

    def test_engine_restored_after_capture_error(self):
        import core
        from unittest import mock
        eng = _Engine()
        with mock.patch.object(core, "capture_keys", side_effect=RuntimeError("hook")), \
                mock.patch.object(core, "log_error"):
            r = self.api(eng).capture_hotkey("normal", 1)
        self.assertFalse(r["ok"])
        self.assertEqual(eng.calls[-2:], ["resume", "end"])


class TestCaptureExclusion(unittest.TestCase):
    """التقاط الزرار والتسجيل مايحصلوش مع بعض أبدًا — نفس القفل."""

    def make(self):
        import core
        app = core.App.__new__(core.App)
        app.recording, app.busy, app.capturing, app._op = False, False, False, None
        return app

    def test_capture_blocks_begin(self):
        import core
        from unittest import mock
        app = self.make()
        self.assertTrue(app.try_begin_capture())
        with mock.patch.object(core, "_foreground_app", return_value=""):
            app.begin("normal")
        self.assertFalse(app.recording)

    def test_recording_blocks_capture(self):
        app = self.make()
        app.recording = True
        self.assertFalse(app.try_begin_capture())
        self.assertFalse(app.capturing)

    def test_race_never_leaves_both(self):
        import threading
        import core
        from unittest import mock
        for _ in range(50):
            app = self.make()
            app.rec = mock.Mock(ensure_open=mock.Mock(return_value=True))
            barrier = threading.Barrier(2, timeout=5)

            def do_begin():
                barrier.wait()
                app.begin("normal")

            def do_capture():
                barrier.wait()
                app.try_begin_capture()

            with mock.patch.object(core, "_foreground_app", return_value=""), \
                    mock.patch.object(core, "_probe_password"), \
                    mock.patch.object(core.App, "_begin_tail"):
                threads = [threading.Thread(target=do_begin), threading.Thread(target=do_capture)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(5)
                    self.assertFalse(t.is_alive())
            # واحد بس كسب: لو الاتنين عدّوا يبقى القفل مش مشترك، ولو ولا واحد يبقى فيه ثريد وقع
            self.assertEqual(int(app.recording) + int(app.capturing), 1)


if __name__ == "__main__":
    unittest.main()
