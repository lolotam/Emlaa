# -*- coding: utf-8 -*-
"""
اختبارات Task 16 — توصيل التفريغ بدون إنترنت بخط process في core.App + Api الإعدادات.
مفيش شبكة ولا مفاتيح ولا BASE الحقيقي: offline.installed/transcribe مزيّفين،
والعميل مزيّف، والحافظة والحقن stubs — بنختبر القرار الفعلي مش الاستدعاءات.
"""
import os
import sys
import threading
import unittest
from unittest import mock

# source مش حزمة (مفيش __init__.py)، فبنضيفه للمسار عشان الاستيراد يشتغل من جذر الـrepo
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source"))

import core       # noqa: E402
import offline    # noqa: E402
import providers  # noqa: E402
import app_web    # noqa: E402


def make_app():
    """App من غير __init__ عشان مافتحناش ميكروفون حقيقي."""
    app = core.App.__new__(core.App)
    app.rec = None
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


def cfg(**over):
    c = dict(core.DEFAULTS)
    c.update(over)
    return c


class NetworkFailingClient:
    """عميل مزوّد وهمي: transcribe بيرمي الخطأ اللي نحطّه (NetworkError افتراضيًا)."""

    def __init__(self, err=None):
        self.vocab = []
        self.vocab_extra = []
        self.err = err or providers.NetworkError("انقطاع في النت")

    def transcribe(self, wav, lang):
        raise self.err


# معلومات فوكس ثابتة: هدف عادي (مش باسورد) — عشان منعتمدش على النافذة الحقيقية
GUI_FOCUS = {"is_password": False, "class": "Edit", "editable": True}


def _wire(tc, offline_mode="fallback", installed="base", offline_text="النص المحلي"):
    """
    بيشغّل كل الـpatches المشتركة ويرجّع dict فيه الموكس اللي بنأكّد عليها.
    بيسجّل p.stop كـcleanup — مش نتيجة start() — عشان الترقيعة تتفك فعلًا بعد الاختبار.
    """
    m = {
        "paste": mock.Mock(return_value="placed"),
        "history": mock.Mock(return_value=111),
        "clip": mock.Mock(return_value=True),
        "transcribe": mock.Mock(return_value=offline_text),
        "installed": mock.Mock(return_value=installed),
    }

    def start(patcher):
        patcher.start()
        tc.addCleanup(patcher.stop)

    start(mock.patch.object(core, "CFG", cfg(offline_mode=offline_mode)))
    start(mock.patch("winput.focused_info", return_value=dict(GUI_FOCUS)))
    start(mock.patch.object(core, "_foreground_app", return_value=""))
    start(mock.patch.object(core, "log_error"))
    start(mock.patch.object(core, "paste_text", m["paste"]))
    start(mock.patch.object(core, "history_add", m["history"]))
    start(mock.patch.object(core, "recording_save"))
    start(mock.patch.object(core, "_copy_to_clipboard", m["clip"]))
    start(mock.patch.object(offline, "installed", m["installed"]))
    start(mock.patch.object(offline, "transcribe", m["transcribe"]))
    return m


class TestAlwaysOffline(unittest.TestCase):
    """offline_mode="always" + موديل مثبّت = مفيش بناء Client ولا نداء موديل."""

    def test_normal_uses_offline_and_never_builds_client(self):
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="كلام محلي")
        app.process("WAV", core.Operation(mode="normal"))
        app.client.assert_not_called()
        m["transcribe"].assert_called_once_with("WAV", "ar")
        m["paste"].assert_called_once_with("كلام محلي", ("gui", "type", "كلام محلي"))
        self.assertEqual(app.texts, ["كلام محلي"])
        self.assertEqual(app.events[-1], ("done", "اتفرّغ من غير إنترنت (من غير تحسين)"))

    def test_snippet_expands_offline(self):
        # توسيع الاختصار محلي بالكامل — offline بيشيل لفة الموديل بس، مش الاختصارات
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="العنوان بتاعي")
        core.CFG["snippets"] = [{"trigger": "العنوان بتاعي", "text": "١٢ شارع النيل"}]
        app.process("WAV", core.Operation(mode="normal"))
        app.client.assert_not_called()
        self.assertEqual(m["paste"].call_args.args[0], "١٢ شارع النيل")
        self.assertTrue(m["paste"].call_args.kwargs.get("from_snippet"))
        self.assertEqual(m["history"].call_args.args[2], "[اختصار] العنوان بتاعي")

    def test_snippet_not_expanded_into_password_field_offline(self):
        app = make_app()
        m = _wire(self, offline_mode="always", offline_text="العنوان بتاعي")
        core.CFG["snippets"] = [{"trigger": "العنوان بتاعي", "text": "١٢ شارع النيل"}]
        with mock.patch("winput.focused_info", return_value=dict(GUI_FOCUS, is_password=True)):
            app.process("WAV", core.Operation(mode="normal"))
        for call in m["paste"].call_args_list:
            self.assertNotIn("١٢ شارع النيل", call.args[0])

    def test_prompt_copies_not_inserts(self):
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="طلب محلي")
        app.process("WAV", core.Operation(mode="prompt"))
        app.client.assert_not_called()
        m["paste"].assert_not_called()
        m["clip"].assert_called_once_with("طلب محلي")
        self.assertEqual(app.unplaced, ["طلب محلي"])
        self.assertEqual(app.events[-1], ("done", "اتفرّغ بس — التحويل محتاج إنترنت"))
        self.assertEqual(m["history"].call_args.args[2], "طلب محلي")

    def test_translate_copies_and_keeps_raw_history(self):
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="نص عربي")
        app.process("WAV", core.Operation(mode="translate"))
        app.client.assert_not_called()
        self.assertEqual(app.unplaced, ["نص عربي"])
        self.assertEqual(m["history"].call_args.args[1], "نص عربي")  # raw
        self.assertEqual(m["history"].call_args.args[2], "نص عربي")  # result = raw
        self.assertEqual(app.events[-1], ("done", "اتفرّغ بس — التحويل محتاج إنترنت"))

    def test_history_engine_is_offline(self):
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", installed="small-q5_1", offline_text="نص")
        app.process("WAV", core.Operation(mode="normal"))
        engine = m["history"].call_args.kwargs["engine"]
        self.assertEqual(engine, {"stt": "offline", "stt_model": "whisper.cpp small-q5_1"})

    def test_edit_mode_offline_rejects_without_insert(self):
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always")
        app.process("WAV", core.Operation(mode="edit"))
        app.client.assert_not_called()
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "التعديل محتاج إنترنت"))

    def test_always_not_installed_refuses_without_client(self):
        # N1: وضع "always" ومفيش موديل مثبّت — منبنيش Client ولا ننادي أي مزوّد،
        # نرفض بـ"مش متثبّت" من غير سجل ولا حافظة
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", installed=None)
        app.process("WAV", core.Operation(mode="normal"))
        app.client.assert_not_called()
        m["transcribe"].assert_not_called()
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        m["clip"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "التفريغ من غير إنترنت مش متثبّت — نزّله من الإعدادات"))

    def test_edit_always_not_installed_refuses_without_client(self):
        # N1: تعديل + "always" + مفيش موديل — رفض "التعديل محتاج إنترنت" برضه
        # من غير ما نبني Client (سواء الموديل متثبّت ولا لأ)
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", installed=None)
        app.process("WAV", core.Operation(mode="edit"))
        app.client.assert_not_called()
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "التعديل محتاج إنترنت"))


class TestFallbackOffline(unittest.TestCase):
    """offline_mode="fallback" = العميل الأول؛ لو النت وقع والموديل مثبّت → offline."""

    def test_normal_falls_back_after_network_error(self):
        app = make_app()
        app.client = lambda: NetworkFailingClient()
        m = _wire(self, offline_mode="fallback", offline_text="اتفرّغ محليًا")
        app.process("WAV", core.Operation(mode="normal"))
        m["transcribe"].assert_called_once_with("WAV", "ar")
        m["paste"].assert_called_once_with("اتفرّغ محليًا", ("gui", "type", "اتفرّغ محليًا"))
        self.assertEqual(app.events[-1], ("done", "اتفرّغ من غير إنترنت (من غير تحسين)"))

    def test_prompt_falls_back_and_copies(self):
        app = make_app()
        app.client = lambda: NetworkFailingClient()
        m = _wire(self, offline_mode="fallback", offline_text="كلام")
        app.process("WAV", core.Operation(mode="prompt"))
        self.assertEqual(app.unplaced, ["كلام"])
        m["paste"].assert_not_called()
        self.assertEqual(app.events[-1], ("done", "اتفرّغ بس — التحويل محتاج إنترنت"))

    def test_translate_falls_back(self):
        app = make_app()
        app.client = lambda: NetworkFailingClient()
        m = _wire(self, offline_mode="fallback", offline_text="كلام")
        app.process("WAV", core.Operation(mode="translate"))
        self.assertEqual(app.unplaced, ["كلام"])
        self.assertEqual(app.events[-1], ("done", "اتفرّغ بس — التحويل محتاج إنترنت"))

    def test_http_401_does_not_fall_back(self):
        app = make_app()
        app.client = lambda: NetworkFailingClient(RuntimeError("401 invalid api key"))
        m = _wire(self, offline_mode="fallback", offline_text="مينفعش يتفرّغ")
        app.process("WAV", core.Operation(mode="normal"))
        m["transcribe"].assert_not_called()
        self.assertEqual(app.events[-1][0], "err")
        self.assertIn("المفتاح", app.events[-1][1])

    def test_edit_mode_fallback_network_error_rejects(self):
        app = make_app()
        app.client = lambda: NetworkFailingClient()
        m = _wire(self, offline_mode="fallback")
        app.process("WAV", core.Operation(mode="edit"))
        m["paste"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.events[-1], ("err", "التعديل محتاج إنترنت"))


class TestFriendlyErrorOffline(unittest.TestCase):
    def test_network_error_without_pack_appends_hint(self):
        with mock.patch.object(offline, "installed", return_value=None):
            msg = core.friendly_error(providers.NetworkError("dns فشل"))
        self.assertIn("مفيش اتصال بالنت", msg)
        self.assertIn("تقدر تنزّل التفريغ من غير إنترنت من الإعدادات", msg)

    def test_network_error_with_pack_keeps_plain_message(self):
        with mock.patch.object(offline, "installed", return_value="base"):
            msg = core.friendly_error(providers.NetworkError("dns فشل"))
        self.assertIn("مفيش اتصال بالنت", msg)
        self.assertNotIn("تقدر تنزّل", msg)

    def test_offline_corrupt_message_passes_through(self):
        # T20: رسالة الموديل البايظ لازم توصل للمستخدم زي ما هي — مش «مشكلة مش متوقّعة»
        msg = "الموديل المحلي بايظ — شيله ونزّله تاني من الإعدادات"
        self.assertEqual(core.friendly_error(RuntimeError(msg)), msg)


class _Ctrl:
    """وحدة تحكم مزيّفة لـApi — الحقول اللي bootstrap/save_settings محتاجاها."""

    version = "0"
    brand = {"name": "x", "url": "y"}
    state = "ready"
    last_text = ""
    update_info = None
    hotkeys = []
    engine = None

    def apply_lang(self): pass
    def start_engine(self): pass
    def start_open_hotkey(self): pass
    def tk_call(self, fn): pass
    def push(self, fn, payload): pass


class TestApiOffline(unittest.TestCase):
    def test_save_settings_no_key_always_installed_ok(self):
        api = app_web.Api(_Ctrl())
        with mock.patch.object(providers, "read_keys", return_value={}), \
                mock.patch.object(offline, "installed", return_value="base"), \
                mock.patch.object(core, "save_config"), \
                mock.patch.object(core, "history_prune"), \
                mock.patch.object(core, "history_stats",
                                  return_value={"words": 0, "count": 0, "wpm": None, "saved_min": 0.0}), \
                mock.patch.object(core, "_is_packaged", return_value=False), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            r = api.save_settings({"provider": "groq", "offline_mode": "always"})
        self.assertTrue(r["ok"])

    def test_save_settings_no_key_no_offline_requires_key(self):
        api = app_web.Api(_Ctrl())
        with mock.patch.object(providers, "read_keys", return_value={}), \
                mock.patch.object(offline, "installed", return_value=None), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            r = api.save_settings({"provider": "groq"})
        self.assertFalse(r["ok"])
        self.assertIn("محتاج مفتاح", r["err"])

    def test_offline_download_refuses_concurrent(self):
        api = app_web.Api(_Ctrl())
        started = threading.Event()
        release = threading.Event()

        def fake_download(model, progress=None):
            started.set()
            release.wait(5)

        with mock.patch.object(offline, "download", fake_download), \
                mock.patch.object(core, "log_error"):
            r1 = api.offline_download("base")
            self.assertTrue(r1["ok"])
            r2 = api.offline_download("base")
            self.assertFalse(r2["ok"])
            self.assertIn("شغّال", r2["err"])
            release.set()
            self.assertTrue(started.wait(5))

    def test_offline_status_exposes_verified(self):
        # T20: verified بييجي من cached_verification (من غير هاش جوه offline_status)
        api = app_web.Api(_Ctrl())
        with mock.patch.object(offline, "installed", return_value="base"), \
                mock.patch.object(offline, "residual", return_value=False), \
                mock.patch.object(offline, "cached_verification", return_value=True), \
                mock.patch.object(core, "CFG", dict(core.DEFAULTS)):
            r = api.offline_status()
        self.assertIs(r["verified"], True)



class TestOfflineHandoffNeverCopiesPasswords(unittest.TestCase):
    def test_prompt_offline_in_password_field_copies_nothing(self):
        # برومبت offline والتسجيل كان في خانة باسورد: النص ممنوع يروح للحافظة أو السجل
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="كلمة السر")
        with mock.patch("winput.focused_info",
                        return_value={"is_password": True, "class": "", "editable": True}):
            app.process("WAV", core.Operation(mode="prompt"))
        m["clip"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.unplaced, [])
        self.assertEqual(app.events[-1][0], "err")

    def test_late_password_focus_copies_nothing(self):
        # N2: الفوكس وقت التفريغ مش باسورد، بس وقت التسليم اتنقل لخانة باسورد —
        # الفحص المتأخر لازم يرفض من غير نسخ ولا سجل ولا on_unplaced
        app = make_app()
        app.client = mock.Mock(side_effect=AssertionError("Client اتبنى رغم وضع offline"))
        m = _wire(self, offline_mode="always", offline_text="كلمة السر")
        focus = [dict(GUI_FOCUS), {"is_password": True, "class": "", "editable": True}]

        def focused():
            return focus.pop(0) if focus else {"is_password": True, "class": "", "editable": True}

        with mock.patch("winput.focused_info", side_effect=focused):
            app.process("WAV", core.Operation(mode="prompt"))
        m["clip"].assert_not_called()
        m["history"].assert_not_called()
        self.assertEqual(app.unplaced, [])
        self.assertEqual(app.events[-1][1], "مينفعش أنسخ نص خانة باسورد — التحويل محتاج إنترنت")


class TestClassicKeylessSave(unittest.TestCase):
    """الواجهة الكلاسيك: offline دايمًا + موديل مثبّت = الإعدادات بتتحفظ من غير مفتاح."""

    def _ui(self, mode, installed):
        import emlaa
        ui = emlaa.EmlaaClassic.__new__(emlaa.EmlaaClassic)
        ui.cfg = cfg(offline_mode=mode)
        ui._key_drafts = {}
        ui.skey_var = mock.Mock(get=mock.Mock(return_value=""))
        ui._settings_pid = mock.Mock(return_value="groq")
        ui._apply = mock.Mock()
        ui._set_smsg = mock.Mock()
        p = mock.patch.object(offline, "installed", return_value=installed)
        p.start(); self.addCleanup(p.stop)
        k = mock.patch.object(providers, "read_keys", return_value={})
        k.start(); self.addCleanup(k.stop)
        return ui

    def test_saves_without_key_in_always_with_pack(self):
        ui = self._ui("always", "base")
        ui._save()
        ui._apply.assert_called_once_with("groq", "", verified=False)

    def test_still_requires_key_otherwise(self):
        for mode, inst in (("fallback", "base"), ("always", None)):
            ui = self._ui(mode, inst)
            ui._save()
            ui._apply.assert_not_called()

    def test_apply_never_writes_an_empty_key(self):
        import emlaa
        ui = emlaa.EmlaaClassic.__new__(emlaa.EmlaaClassic)
        with mock.patch.object(providers, "write_key") as wk,                 mock.patch.object(core, "save_config", side_effect=RuntimeError("stop")):
            ui.cfg = cfg()
            for name in ("hk_norm_var", "hk_prmt_var", "hk_trns_var", "polish_var", "prompt_var",
                         "paste_var", "tray_var", "upd_var", "float_var"):
                setattr(ui, name, mock.Mock(get=mock.Mock(return_value="")))
            with self.assertRaises(RuntimeError):
                ui._apply("groq", "", verified=False)
        wk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
