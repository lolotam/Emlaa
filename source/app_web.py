"""
إملاء — الواجهة الجديدة (HTML/CSS جوّه نافذة ويندوز عن طريق pywebview).

ليه التقسيمة دي:
- pywebview لازم ياخد الثريد الرئيسي، فـTk (الموجة العائمة + نافذة النتيجة)
  بيشتغل في ثريد لوحده — كل نداء ليه بيعدّي من tk_call().
- المحرّك (core.App) والتراي والحافظة والاختصار العام كلهم ثريدات جانبية.
- لو WebView2 أو pywebview مش موجودين، emlaa.py بيرجع للواجهة القديمة (Tk).
"""
import json
import os
import threading
import time
import webbrowser

import core
import providers
import smart
import offline

UI_DIR = "ui"
KEY_WRITE_ERR = "معرفتش أحفظ ملف المفاتيح — المفاتيح القديمة زي ما هي، جرّب تاني"
KEY_STALE_ERR = "قايمة المفاتيح اتغيّرت — جرّب تاني"

OPEN_HOTKEYS = [
    ("<ctrl>+<alt>+n",       "Ctrl + Alt + N"),
    ("<ctrl>+<shift>+<space>", "Ctrl + Shift + Space"),
    ("<ctrl>+<alt>+<space>", "Ctrl + Alt + Space"),
    ("<ctrl>+<shift>+n",     "Ctrl + Shift + N"),
    ("<alt>+<shift>+n",      "Alt + Shift + N"),
    ("",                     "مفيش"),
]


def ui_path(name):
    return core.asset(os.path.join(UI_DIR, name))


def _warm_offline_check():
    """
    بيسخّن فحص بصمة الموديل المحلي في ثريد جانبي (#6): لو الموديل مثبّت، نفحصه
    مرة واحدة في الجلسة عشان offline_status يعرض حالته (سليم/بايظ) من غير ما
    الواجهة تفضل محبوسة على هاش 150–190 MB. الفشل بيتسجّل ومبيطلعش.
    """
    if not offline.installed():
        return

    def run():
        try:
            offline.verify()
        except Exception as e:
            core.log_error(e, "offline/verify-warm")

    threading.Thread(target=run, daemon=True).start()


def combo_listener(combo, fire):
    """
    اختصار عام زي "<ctrl>+<alt>+n" بيتقارن بأكواد الزراير (vk) مش بالحروف.
    ليه مش GlobalHotKeys بتاع pynput: على ويندوز وانت ماسك Ctrl+Alt، حرف N
    بيوصل كود من غير حرف (<78>) فالاختصار عمره ما بيتطابق — وكمان الكيبورد
    العربي بيبعت «ى» بدل n. الكود ثابت مهما كانت اللغة.
    """
    from pynput import keyboard
    K = keyboard.Key
    MODS = {K.ctrl: "ctrl", K.ctrl_l: "ctrl", K.ctrl_r: "ctrl", K.alt: "alt", K.alt_l: "alt",
            K.alt_r: "alt", K.alt_gr: "alt", K.shift: "shift", K.shift_l: "shift", K.shift_r: "shift",
            K.cmd: "win", K.cmd_l: "win", K.cmd_r: "win", K.space: "space"}
    want = set()
    for part in combo.lower().split("+"):
        part = part.strip().strip("<>")
        if part in ("ctrl", "alt", "shift", "win", "space"):
            want.add(part)
        elif len(part) == 1 and part.isalnum():
            want.add("vk%d" % ord(part.upper()))
        elif part:
            raise ValueError("اختصار مش مفهوم: " + combo)

    def token(key):
        if key in MODS:
            return MODS[key]
        vk = getattr(key, "vk", None)
        if vk is None and getattr(key, "value", None) is not None:
            vk = getattr(key.value, "vk", None)
        return "vk%d" % vk if vk else None

    down = set()
    fired = [False]

    def on_press(key):
        t = token(key)
        if t:
            down.add(t)
        if down == want and not fired[0]:
            fired[0] = True
            threading.Thread(target=fire, daemon=True).start()

    def on_release(key):
        down.discard(token(key))
        if not down >= want:
            fired[0] = False

    l = keyboard.Listener(on_press=on_press, on_release=on_release)
    l.daemon = True
    l.start()
    return l


class Controller:
    def __init__(self, version, brand_name, brand_url):
        import emlaa                                  # WaveOverlay / ResultToast / FailedToast
        self.emlaa = emlaa
        self.version = version
        self.brand = {"name": brand_name, "url": brand_url}
        self.engine = None
        self.window = None
        self.tray = None
        self.root = None
        self.wave = None
        self.state = "ready"
        self.last_text = ""
        self.update_info = None
        self._updating = False
        core.cleanup_update_leftovers()         # النسخة القديمة بعد آخر تحديث
        self._tk_ready = threading.Event()
        self._open_hk = None
        self.clip = None
        self._quitting = False
        self._visible = True

    # ═══════════ Tk في ثريد لوحده (الموجة + نافذة النتيجة) ═══════════
    def _tk_thread(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.engine = None
        root._quitting = False
        root.report_callback_exception = lambda et, ev, tb: core.log_error(ev, "ui/tk-callback")
        self.root = root
        self._tk_ready.set()
        root.mainloop()

    def tk_call(self, fn):
        if self.root is not None:
            try:
                self.root.after(0, fn)
            except Exception as e:
                core.log_error(e, "ui/tk_call")

    def _wave(self):
        W = self.emlaa.WaveOverlay
        if self.wave is not None:
            try:
                alive = bool(self.wave.winfo_exists())
            except Exception:
                alive = False
            if not alive:
                core.log_error(RuntimeError("الموجة العائمة كانت ممسوحة — اتعملت من جديد"), "overlay/recreate")
                self.wave = None
        if self.wave is None:
            self.wave = W(self.root, on_click=lambda: self.toggle_record("normal"),
                          on_menu=self.show_window,
                          on_cancel=lambda: self.engine and self.engine.cancel())
        return self.wave

    # ═══════════ الحالة (من المحرّك) ═══════════
    def set_state(self, st, msg=None):
        mode = None
        if msg in self.emlaa.WaveOverlay.MODE_COLORS:      # core بيبعت الوضع مكان الرسالة
            mode, msg = msg, None
        self.state = st

        def ui():
            W = self.emlaa.WaveOverlay
            if st == "rec" or W.enabled():
                w = self._wave()
                w.set_state(st, mode=mode or ("normal" if st == "rec" else None))
            elif self.wave is not None:
                try:
                    self.wave.set_state(st, mode=mode)
                except Exception:
                    pass
        self.tk_call(ui)
        self.push("onState", {"state": st, "msg": msg, "mode": mode})
        if st in ("done", "err"):
            self.push("onHistory", None)

    def on_text(self, text):
        self.last_text = text

    def on_unplaced(self, text):
        self.tk_call(lambda: self.emlaa.ResultToast.show_for(self.root, text))

    def on_failed(self, rid, message):
        self.tk_call(lambda: self.emlaa.FailedToast.show_for(
            self.root, message, lambda: self.show_window("history")))

    def _wire(self, app):
        app.on_state = self.set_state
        app.on_text = self.on_text
        app.on_unplaced = self.on_unplaced
        app.on_failed = self.on_failed

    def push(self, fn, payload):
        """بيبعت حدث للواجهة (لو مفتوحة)."""
        w = self.window
        if w is None:
            return
        try:
            w.evaluate_js(f"window.emlaa && emlaa.{fn}({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    # ═══════════ المحرّك ═══════════
    # إضافة مفتاح والحفظ الاتنين بيشغّلوا المحرك لو مش شغّال — وهو لسه بيقوم (engine لسه
    # None) نداء تاني كان هيعمل محرك تاني بمستمع زراير تاني
    _engine_lock = threading.Lock()
    _engine_booting = False

    def start_engine(self):
        with self._engine_lock:
            if self.engine is not None or self._engine_booting:
                return
            self._engine_booting = True

        def boot():
            try:
                app = core.App()
                self._wire(app)
                try:
                    app.start_hotkey()
                except Exception:
                    # المحرك مايتسجّلش نص شغّال: غير كده start_engine كان هيرفض أي محاولة تانية
                    app.shutdown()
                    raise
                self.engine = app
                if self.root is not None:
                    self.root.engine = app
                self.set_state("ready")
            except Exception as e:
                core.log_error(e, "engine/boot")
                s = str(e).lower()
                self.set_state("err", "مفيش ميكروفون متوصّل" if "device" in s or "portaudio" in s
                               else "الميكروفون مش شغّال")
            finally:
                self._engine_booting = False
        threading.Thread(target=boot, daemon=True).start()

    def toggle_record(self, mode="normal"):
        e = self.engine
        if not e:
            return False
        if e.recording:
            e.end()
        else:
            e.begin(mode=mode or "normal")
        return True

    # ═══════════ النافذة ═══════════
    def show_window(self, page=None):
        w = self.window
        if w is None:
            return
        try:
            w.show()
            w.restore()
            w.on_top = True                    # يجيبها قدّام فعلًا حتى لو برنامج تاني ماسك الفوكس
            w.on_top = False
            self._visible = True
            if page:
                self.push("go", page)
        except Exception as e:
            core.log_error(e, "window/show")

    def hide_window(self):
        try:
            self.window.hide()
            self._visible = False
        except Exception as e:
            core.log_error(e, "window/hide")

    def _on_closing(self):
        if self._quitting:
            return True
        if core.CFG.get("minimize_to_tray", True) and self.tray is not None:
            threading.Thread(target=self.hide_window, daemon=True).start()
            return False                       # نلغي القفل — يستخبّى جنب الساعة
        threading.Thread(target=self.quit, daemon=True).start()
        return False

    def _flush_ui_settings(self, timeout=3.0):
        """
        الواجهة بتحفظ الإعدادات لوحدها — حفظة لسه شغّالة (أو مستنية الكتابة) لازم تخلص قبل
        ما النافذة تتقفل. flushSave بترجّع Promise فالـcallback بيتنده لما تخلص؛ لو الواجهة
        مش موجودة أو علّقت، القفل بيكمّل بعد المهلة.
        """
        done = threading.Event()
        try:
            self.window.evaluate_js(
                "window.emlaa && window.emlaa.flushSave ? window.emlaa.flushSave() : Promise.resolve(null)",
                lambda _result: done.set())
            done.wait(timeout)
        except Exception as e:
            core.log_error(e, "quit/flush-settings")

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self._flush_ui_settings()
        for fn in (lambda: self.tray and self.tray.stop(),
                   lambda: self.engine and self.engine.shutdown(),
                   lambda: self._open_hk and self._open_hk.stop(),
                   lambda: self.clip and self.clip.stop()):
            try:
                fn()
            except Exception:
                pass
        if self.root is not None:
            self.root._quitting = True
            self.tk_call(self.root.quit)
        try:
            self.window.destroy()
        except Exception:
            pass

    # ═══════════ التراي / الاختصار العام / الحافظة / التحديث ═══════════
    def _tray_menu(self):
        import pystray
        en = core.CFG.get("lang") == "en"
        T = (lambda ar, e: e if en else ar)
        return pystray.Menu(
            pystray.MenuItem(T("فتح إملاء", "Open Emlaa"), lambda: self.show_window(), default=True),
            pystray.MenuItem(T("السجل", "History"), lambda: self.show_window("history")),
            pystray.MenuItem(T("الحافظة", "Clipboard"), lambda: self.show_window("clipboard")),
            pystray.MenuItem(T("الإعدادات", "Settings"), lambda: self.show_window("settings")),
            pystray.MenuItem(T("تسجيل / إيقاف", "Record / stop"), lambda: self.toggle_record("normal")),
            pystray.MenuItem(T("تفريغ حرفي (من غير تحسين)", "Raw transcription (no polish)"),
                             lambda: self.toggle_raw(),
                             checked=lambda item: not core.CFG.get("polish", True)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(T("خروج", "Quit"), lambda: self.quit()),
        )

    def _tray_title(self):
        return "Emlaa — voice to text" if core.CFG.get("lang") == "en" else "إملاء — صوت إلى نص عربي"

    def toggle_raw(self):
        """
        «تفريغ حرفي» من قايمة التراي: يقلب «تنظيف النص» من غير ما المستخدم
        يفتح الإعدادات — حاجة يتكرّر عليها بسرعة (تفريغ طويل وهوينفع يكون
        زي ما اتقال، بالظبط). العلم بيتحفظ ويوصل للواجهة عشان مفتاح
        الإعدادات يبان صح، والقايمة بتتحدّث علشان علامة الصح تأخذ مكانها.
        إعادة رسم الموجة (علامة «خام» فوق الكبسولة) لازم تيجي من ثريد Tk
        فبيتمرّرها عبر tk_call() زي set_state().
        """
        core.CFG["polish"] = not core.CFG.get("polish", True)
        core.save_config(core.CFG)
        self.push("onConfig", {"polish": core.CFG["polish"]})
        try:
            if self.tray is not None:
                self.tray.update_menu()
        except Exception as e:
            core.log_error(e, "tray/raw-toggle")

        def redraw():
            w = self.wave
            if w is None:
                return
            try:
                if not bool(w.winfo_exists()):
                    return
                # الكبسولة الكبيرة بس عندها «خام» — الزرار الصغير (idle)
                # لي رسم تاني، فـ_draw هيرسمه غلط فوقه
                if w._state not in ("rec", "work", "prompt", "translate"):
                    return
            except Exception:
                return
            try:
                w._draw(getattr(w, "_lvl", 0.0))
            except Exception:
                pass
        self.tk_call(redraw)

    def apply_lang(self):
        """بعد تغيير اللغة: قايمة التراي وعنوان النافذة بيتغيّروا علطول."""
        try:
            if self.tray is not None:
                self.tray.menu = self._tray_menu()
                self.tray.title = self._tray_title()
                self.tray.update_menu()
        except Exception as e:
            core.log_error(e, "tray/lang")
        try:
            self.window.set_title("Emlaa" if core.CFG.get("lang") == "en" else "إملاء")
        except Exception:
            pass

    def start_tray(self):
        def run():
            try:
                pystray = core.import_pystray()
                from PIL import Image
                img = Image.open(core.asset("emlaa.png"))
                self.tray = pystray.Icon("emlaa", img, self._tray_title(), self._tray_menu())
                self.tray.run()
            except Exception as e:
                core.log_error(e, "tray/start")
                self.tray = None
        threading.Thread(target=run, daemon=True).start()

    def start_open_hotkey(self):
        try:
            if self._open_hk:
                self._open_hk.stop()
        except Exception:
            pass
        self._open_hk = None
        combo = (core.CFG.get("open_hotkey") or "").strip()
        if not combo:
            return
        try:
            self._open_hk = combo_listener(combo, lambda: self.show_window())
        except Exception as e:
            core.log_error(e, "open-hotkey")

    def start_clipboard(self):
        self.clip = core.ClipboardWatcher(on_new=lambda e: self.push("onClip", e))
        self.clip.start()

    def watch_show_request(self):
        def run():
            while not self._quitting:
                try:
                    if os.path.exists(core.SHOW_PATH):
                        os.remove(core.SHOW_PATH)
                        self.show_window()
                except Exception:
                    pass
                time.sleep(1.0)
        threading.Thread(target=run, daemon=True).start()

    def check_update(self, force=False):
        if not force and not (core.CFG.get("check_updates", True) or core.CFG.get("auto_update", True)):
            return None
        info = core.check_update(self.version)
        self.update_info = info
        return info

    def watch_updates(self):
        """أول ما البرنامج يفتح وبعدين كل 6 ساعات: لو فيه إصدار جديد نبلّغ مرة واحدة لكل إصدار."""
        if core.STORE:
            return                               # الـStore هو اللي بيحدّث
        def run():
            told = None
            time.sleep(4)
            while not self._quitting:
                info = self.check_update()
                if info and info["version"] != told:
                    told = info["version"]
                    if core.CFG.get("auto_update", True) and info.get("can_install"):
                        self._auto_install(info)
                        return
                    self.push("onUpdate", info)
                    self.tray_notify(
                        f"Emlaa v{info['version']} is available — open Emlaa to install it"
                        if core.CFG.get("lang") == "en" else
                        f"فيه نسخة جديدة من إملاء v{info['version']} — افتح البرنامج عشان تثبّتها")
                for _ in range(6 * 3600):
                    if self._quitting:
                        return
                    time.sleep(1)
        threading.Thread(target=run, daemon=True).start()

    def _busy(self):
        e = self.engine
        return bool(e and (getattr(e, "recording", False) or getattr(e, "busy", False)))

    def _auto_install(self, info):
        """التحديث التلقائي: نستنى لحد ما مفيش تسجيل شغّال، وبعدين ننزّل ونثبّت من غير سؤال."""
        while self._busy() and not self._quitting:
            time.sleep(2)
        time.sleep(3)                              # لو المستخدم بدأ تسجيل تاني على طول
        while self._busy() and not self._quitting:
            time.sleep(2)
        if self._quitting:
            return
        self.push("onUpdate", dict(info, auto=True))
        self.tray_notify(
            f"Installing Emlaa v{info['version']} — it will restart by itself"
            if core.CFG.get("lang") == "en" else
            f"بيثبّت إملاء v{info['version']} — هيعيد التشغيل لوحده")
        self.install_update()

    def tray_notify(self, msg):
        try:
            if self.tray is not None and getattr(self.tray, "HAS_NOTIFICATION", True):
                self.tray.notify(msg, "Emlaa" if core.CFG.get("lang") == "en" else "إملاء")
        except Exception as e:
            core.log_error(e, "tray/notify")

    def install_update(self):
        """تنزيل + تثبيت في الخلفية. الواجهة بتتابع بـ onUpdateProgress / onUpdateError."""
        info = self.update_info
        if self._updating or not info or not info.get("asset_url") or not core.can_self_update():
            return False
        self._updating = True

        def run():
            try:
                tmp = core.download_update(info, lambda p: self.push("onUpdateProgress", p), self.version)
                self.push("onUpdateProgress", 100)
                core.install_update(tmp)
                time.sleep(1.2)                      # الواجهة تلحق تعرض «بيعيد التشغيل»
                self.quit()
            except Exception as e:
                core.log_error(e, "update/install")
                self.push("onUpdateError", str(e)[:200])
            finally:
                self._updating = False
        threading.Thread(target=run, daemon=True).start()
        return True

    # ═══════════ التشغيل ═══════════
    def run(self):
        import webview
        core.preload_pystray()
        threading.Thread(target=self._tk_thread, daemon=True).start()
        self._tk_ready.wait(5)

        api = Api(self)
        self.window = webview.create_window(
            "Emlaa" if core.CFG.get("lang") == "en" else "إملاء", url=ui_path("index.html"), js_api=api,
            width=1080, height=720, min_size=(960, 640),
            frameless=True, easy_drag=False,
            background_color="#fafafb" if core.CFG.get("theme") == "light" else "#111114",
            text_select=True)
        self.window.events.closing += self._on_closing

        def after_start():
            self.start_tray()
            self.start_clipboard()
            self.start_open_hotkey()
            self.watch_show_request()
            _warm_offline_check()
            if core.can_run():
                self.start_engine()
            self.watch_updates()

        webview.start(after_start, private_mode=False,
                      storage_path=os.path.join(core.BASE, ".webview"))
        # النافذة اتقفلت نهائيًا
        self._quitting = True
        try:
            if self.root is not None:
                self.root.quit()
        except Exception:
            pass


LAST_STT_KEY_ERR = ("ده آخر مفتاح بيفرّغ — لو اتشال مفيش ولا ميزة هتقدر تفرّغ. "
                    "ضيف مفتاح تاني أو نزّل الموديل المحلي الأول")
LOCAL_NAME = "محلي · Whisper"


def _feature_catalog(pools, local):
    """اللي ينفع يتختار في قوايم الميزات: موديلات كل مزوّد وهل ليه مفتاح، والموديل المحلي."""
    catalog = {p: {"name": providers.PROVIDERS[p]["name"],
                   "sttModels": providers.stt_catalog(p),
                   "chatModels": providers.chat_models(p),
                   "hasKey": bool(pools.get(p)),
                   "sttOnly": not providers.PROVIDERS[p].get("chat")}
               for p in providers.ORDER}
    catalog[smart.LOCAL] = {"name": LOCAL_NAME, "installed": local or None}
    return catalog


def _clean_features(features):
    """
    نسخة بالحقول المعروفة بس (بعد validate_features): الواجهة بترجّع الميزات زي ما
    bootstrap بعتها، و«label» وأي حقل عرض تاني مالهمش مكان في config.json.
    """
    def items(lst):
        return [{"provider": str(i["provider"]), "model": str(i.get("model") or "")[:80]} for i in lst]
    return {m: {"hotkey": [int(v) for v in features[m]["hotkey"]],
                "stt": items(features[m]["stt"]),
                "ai": items(features[m]["ai"])}
            for m in smart.FEATURES}


def _hotkey_state(cfg):
    """اللي لو اتغيّر مستمع الزراير لازم يتعاد: زرار كل ميزة + toggle/hold."""
    feats = cfg.get("features") or {}
    return (tuple(tuple((feats.get(m) or {}).get("hotkey") or ()) for m in smart.FEATURES),
            cfg.get("mode"))


class Api:
    """كل الدوال دي بتتنده من الواجهة (JavaScript) — window.pywebview.api.*"""

    def __init__(self, ctrl):
        self._c = ctrl
        # F9: تنزيل offline — تنزيل واحد في نفس الوقت بس (الملفات مشتركة)
        self._offline_lock = threading.Lock()
        self._offline_busy = False
        # Task 24: قفل واحد بيحوّش key_add / key_remove وكتابة المفتاح في save_settings
        # عشان دوستين متتاليتين سريعتين مايخلطوش قراية/كتابة .env فوق بعض.
        self._key_lock = threading.Lock()
        # تسجيل زرار من الإعدادات: جلسة واحدة بس في نفس الوقت
        self._capture_lock = threading.Lock()

    # ── بيانات أول ما الواجهة تفتح ──
    def bootstrap(self):
        c = self._c
        cfg = core.CFG
        pools = providers.read_key_pools(core.ENV_PATH)
        local = offline.installed()
        pid = cfg.get("provider", providers.DEFAULT)
        lang = cfg.get("lang", "ar")
        return {
            "version": c.version,
            "brand": c.brand,
            "hasKey": bool(pools.get(pid)),
            "canRun": core.can_run(pools=pools, local=local),
            "state": c.state,
            "lastText": c.last_text,
            "update": c.update_info,
            "store": core.STORE,
            "offline": {
                "installed": local,
                "packaged": core._is_packaged(),
                "models": [{"id": m, "size": round(sz / 1_000_000)}
                           for m, (_u, _h, sz) in offline.MODELS.items()],
            },
            "providers": [dict(id=p, name=providers.PROVIDERS[p]["name"],
                               tag=providers.PROVIDERS[p]["tag"], desc=providers.PROVIDERS[p]["desc"],
                               keyUrl=providers.PROVIDERS[p]["key_url"],
                               keyHint=providers.PROVIDERS[p]["key_hint"],
                               hasKey=bool(pools.get(p)),
                               keyCount=len(pools.get(p, [])),
                               guide=providers.GUIDES.get(p, {}))
                          for p in providers.ORDER],
            # الواجهة بتعرض الاسم بس — save_settings بيرمي label لو رجعت معاها
            "features": {m: dict(core.feature(m), label=smart.hotkey_label(core.feature(m).get("hotkey"), lang))
                         for m in smart.FEATURES},
            "catalog": _feature_catalog(pools, local),
            "openHotkeys": [{"id": k, "label": v} for k, v in OPEN_HOTKEYS],
            "cfg": {k: cfg.get(k) for k in (
                "provider", "open_hotkey", "mode", "polish", "prompt_mode", "auto_paste", "insert_method", "beep",
                "minimize_to_tray", "check_updates", "auto_update", "floating_button", "clipboard_history",
                "dictionary", "theme", "lang", "history_keep_last10", "models",
                "context_styles", "app_profiles", "snippets")},
            "stats": core.history_stats(),
        }

    # ── السجل ──
    def history(self):
        items = core.history_get(limit=None)       # كله: التسجيلات الفاشلة برّه حد الـ1000
        has = core.recording_ids()
        for i in items:
            i["audio"] = i.get("id") in has
        return {"items": items, "stats": core.history_stats()}

    def history_audio(self, rid):
        """صوت التسجيل base64 عشان الواجهة تشغّله (mp3 صغير: ‏١٠ ثواني ≈ ٨٠ كيلو)."""
        import base64
        try:
            with open(core.recording_path(rid), "rb") as f:
                return {"ok": True, "mime": "audio/mpeg", "data": base64.b64encode(f.read()).decode("ascii")}
        except (OSError, ValueError, TypeError):
            return {"ok": False}

    def history_audio_save(self, rid):
        """نافذة «حفظ باسم» من ويندوز وبعدين نسخة من الـmp3 للمكان اللي اختاره."""
        import shutil
        import webview
        try:
            src = core.recording_path(rid)
        except (ValueError, TypeError):
            return {"ok": False}
        if not os.path.exists(src):
            return {"ok": False}
        item = core.history_entry(rid) or {}
        stamp = (item.get("time") or "").replace(":", "-").replace(" ", "_") or str(rid)
        try:
            kind = webview.FileDialog.SAVE
        except AttributeError:                       # pywebview أقدم من 6
            kind = webview.SAVE_DIALOG
        dest = self._c.window.create_file_dialog(kind, save_filename=f"emlaa_{stamp}.mp3",
                                                 file_types=("MP3 (*.mp3)",))
        if isinstance(dest, (list, tuple)):
            dest = dest[0] if dest else None
        if not dest:
            return {"ok": False, "cancelled": True}
        if not str(dest).lower().endswith(".mp3"):
            dest = str(dest) + ".mp3"
        try:
            shutil.copyfile(src, dest)
            return {"ok": True, "path": dest}
        except OSError as e:
            core.log_error(e, "recordings/download")
            return {"ok": False}

    def history_delete(self, ids):
        core.history_delete(ids)
        return self.history()

    def history_clear(self):
        core.history_clear()
        return self.history()

    def history_retry(self, rid):
        """التفريغ اليدوي — الصفحة مستنية الرد، والنتيجة بتتعرض للنسخ (عمرها ما بتتكتب)."""
        return core.retranscribe(rid)

    # ── الحافظة ──
    def clips(self):
        return core.clip_get()

    def clips_delete(self, ids):
        core.clip_delete(ids)
        return core.clip_get()

    def clips_clear(self):
        core.clip_clear()
        return core.clip_get()          # المفضلة بتفضل

    def clips_fav(self, cid, fav):
        """نجمة على نسخة (أو شيلها). المفضلة مش بتتمسح لا بالمسح ولا بالقص التلقائي."""
        if isinstance(cid, bool) or not isinstance(cid, int):
            return {"ok": False, "err": "النسخة مش موجودة"}
        if not core.clip_set_fav(cid, bool(fav)):
            return {"ok": False, "err": "النسخة مش موجودة"}
        return {"ok": True, "items": core.clip_get()}

    def copy(self, text):
        try:
            import pyperclip
            pyperclip.copy(text or "")
            return True
        except Exception as e:
            core.log_error(e, "ui/copy")
            return False

    # ── القاموس ──
    def dictionary_set(self, words):
        clean, seen = [], set()
        for w in words or []:
            w = str(w).strip()
            if w and w.lower() not in seen:
                seen.add(w.lower()); clean.append(w[:60])
        core.CFG["dictionary"] = clean[:300]
        core.save_config(core.CFG)
        return clean

    # ── الاختصارات الصوتية (F8) ──
    def snippets_set(self, items):
        """
        بيحفظ اختصارات الصوت: قايمة {trigger, text}. المفتاح بيتنضّف من الفراغات،
        والتكرار بيتحدد على الشكل المطبّع (smart.normalize) مش الحرفي — عشان
        «إيميلي» و«ايميلي» مايتسجلوش مرتين ويلخبطوا المطابقة. الفاضي (مفتاح
        أو نص) بيتساقط عشان مايبقاش فيه اختصار ميت.
        """
        clean, seen = [], set()
        for it in items or []:
            if not isinstance(it, dict):
                continue
            trigger = str(it.get("trigger") or "").strip()
            text = str(it.get("text") or "").strip()
            if not trigger or not text:
                continue
            key = smart.normalize(trigger)
            if not key:
                continue
            if key in seen:
                # اتنين بنفس المفتاح (بعد التطبيع) — غالبًا تعديل غيّر مفتاح اختصار لمفتاح
                # اختصار تاني موجود. منحفظش ومنسقطش واحد منهم بصمت؛ المستخدم يقرر
                return {"ok": False, "err": f"فيه اختصار تاني بنفس الجملة «{trigger}» — غيّر واحد منهم"}
            seen.add(key)
            clean.append({"trigger": trigger[:60], "text": text[:2000]})
        core.CFG["snippets"] = clean[:100]
        core.save_config(core.CFG)
        # N7: بنرجّع نفس القايمة المقصوصة اللي اتحفظت (clean[:100]) مش الكاملة —
        # عشان الواجهة تفضل متطابقة مع اللي فعلاً على القرص.
        return clean[:100]

    # ── التسجيل ──
    def record(self, mode="normal"):
        return self._c.toggle_record(mode)

    # ── الإعدادات ──
    def save_settings(self, data):
        """
        data = الإعدادات اللي اتغيّرت بس. features بتتفحص كلها قبل أي حفظ (غلط = مفيش حاجة
        اتغيّرت). شاشة الترحيب بس اللي بتبعت provider (+ key): المفتاح بيتفحص قبل ما يتكتب،
        والميزات اللي المستخدم ماعدّلهاش بتتحسب تاني من المزوّد الجديد.
        """
        c, cfg = self._c, core.CFG
        features = None
        if "features" in data:
            err = smart.validate_features(data["features"])
            if err:
                return {"ok": False, "err": err}
            features = _clean_features(data["features"])
        welcome = "provider" in data
        if welcome:
            err = self._store_welcome_key(data.get("provider"), (data.get("key") or "").strip())
            if err:
                return {"ok": False, "err": err}

        old_hk = _hotkey_state(cfg)
        old_open = cfg.get("open_hotkey")
        for k in ("open_hotkey", "mode", "insert_method"):
            if k in data:
                cfg[k] = data[k]
        if "offline_model" in data:
            cfg["offline_model"] = str(data["offline_model"] or "").strip()[:60]
        # «متعدّلة» بس لو اتغيّرت فعلًا — الواجهة بتبعت features مع أي حفظة (حتى تغيير المظهر)
        if features is not None and features != cfg.get("features"):
            cfg["features"] = features
            cfg["features_custom"] = True
        if welcome:
            cfg["provider"] = data["provider"]
            if not cfg.get("features_custom"):
                cfg["features"] = core.migrated_features(cfg)
        for k in ("polish", "prompt_mode", "auto_paste", "beep", "minimize_to_tray",
                  "check_updates", "auto_update", "floating_button", "clipboard_history", "history_keep_last10",
                  "context_styles"):
            if k in data:
                cfg[k] = bool(data[k])
        # F5: overrides لكل برنامج — {اسم البرنامج: dev/chat/formal} بس، واللي
        # مش سليم (اسم فاضي، قيمة غلط) بيتساقط عشان ما يوصلش للـmodel.
        if "app_profiles" in data and isinstance(data["app_profiles"], dict):
            clean, seen = {}, set()
            for name, prof in data["app_profiles"].items():
                name = str(name).strip().lower()[:60]
                prof = str(prof or "").strip().lower()
                if name and prof in ("dev", "chat", "formal") and name not in seen:
                    seen.add(name)
                    clean[name] = prof
            cfg["app_profiles"] = dict(list(clean.items())[:100])
        if data.get("theme") in ("dark", "light", "system"):
            cfg["theme"] = data["theme"]
        old_lang = cfg.get("lang", "ar")
        if data.get("lang") in ("ar", "en"):
            cfg["lang"] = data["lang"]
        core.save_config(cfg)
        if cfg.get("history_keep_last10", True):
            core.history_prune()
        if cfg.get("lang") != old_lang:
            c.apply_lang()

        if c.engine:
            c.engine.reset_client()
            if old_hk != _hotkey_state(cfg):
                c.engine.restart_hotkey()     # وقت تسجيل/تفريغ بيتأجل لآخر العملية
        elif core.can_run():
            c.start_engine()
        if old_open != cfg.get("open_hotkey"):
            c.start_open_hotkey()

        def wave_setting():
            W = c.emlaa.WaveOverlay
            if c.wave is None and not W.enabled():
                return
            w = c._wave()
            if w._state in ("idle", "ready"):
                w.hide()
        c.tk_call(wave_setting)
        return {"ok": True, "boot": self.bootstrap()}

    def _store_welcome_key(self, pid, new_key):
        """
        مفتاح شاشة الترحيب: بيتفحص (verify) وبعدين يتكتب. من غير مفتاح جديد الحفظ بيعدّي
        بس لو المزوّد ليه مفتاح أو فيه حاجة تانية تفرّغ (الموديل المحلي مثلًا).
        بيرجّع رسالة الغلط أو None.
        """
        if pid not in providers.PROVIDERS:
            return "مزوّد مش معروف"
        if not new_key:
            cfg = core.CFG
            if providers.read_key_pools(core.ENV_PATH).get(pid):
                return None
            # الإعدادات بعد الحفظ: الميزات اللي ماتعدّلتش بتتحسب تاني من المزوّد ده — لازم
            # تفضل تقدر تفرّغ (مش الحالية بس)
            after = cfg if cfg.get("features_custom") else dict(
                cfg, features=core.migrated_features(dict(cfg, provider=pid)))
            if core.can_run(after):
                return None
            return "محتاج مفتاح للمزوّد ده — الصقه في الخانة"
        ok, err = providers.verify(pid, new_key)
        if not ok:
            return err
        with self._key_lock:
            try:
                providers.write_key(core.ENV_PATH, pid, new_key)
            except OSError:
                return KEY_WRITE_ERR
        return None

    # ── تسجيل زرار ميزة من الكيبورد ──
    def capture_hotkey(self, feature, count):
        """
        بيستنى زرار (count=1) أو موديفاير + زرار (count=2) ويرجّعهم مع اسم الميزة اللي
        طلبت — الواجهة بتحط النتيجة في الميزة دي حتى لو المستخدم اتنقل لتاب تاني.
        مرفوض وقت تسجيل/تفريغ: التسجيل والالتقاط مايحصلوش مع بعض.
        """
        if feature not in smart.FEATURES or count not in (1, 2):
            return {"ok": False, "err": "طلب مش مظبوط"}
        if not self._capture_lock.acquire(blocking=False):
            return {"ok": False, "err": "فيه تسجيل زرار شغّال بالفعل"}
        try:
            engine = self._c.engine
            if engine is not None and not engine.try_begin_capture():
                return {"ok": False, "err": "وقّف التسجيل الأول"}
            try:
                if engine is not None:
                    engine.pause_hotkey()
                result = core.capture_keys(count)
            except Exception as e:
                core.log_error(e, "hotkey/capture")
                result = {"ok": False, "err": "مقدرتش أسجّل الزرار — جرّب تاني"}
            finally:
                if engine is not None:
                    engine.resume_hotkey()
                    engine.end_capture()
            return dict(result, feature=feature)
        finally:
            self._capture_lock.release()

    # ── مجمّعة المفاتيح لكل مزوّد (Task 24) ──
    def key_pool(self, pid):
        """
        قايمة المفاتيح المموّهة للمزوّد مع حالة كل واحد — من غير أي مفتاح كامل أبدًا.
        بيعتمد على read_key_pools + key_status، وبيترجّع خطأ لمزوّد مش معروف.
        """
        if pid not in providers.PROVIDERS:
            return {"ok": False, "err": "مزوّد مش معروف"}
        pool = providers.read_key_pools(core.ENV_PATH).get(pid, [])
        keys = []
        for i, k in enumerate(pool):
            st = providers.key_status(pid, k)
            keys.append({"index": i,
                         "id": providers.key_id(k),
                         "masked": providers.mask_key(k),
                         "status": st["status"],
                         "retryIn": st["retry_in"]})
        return {"ok": True, "keys": keys}

    def key_reveal(self, pid, index, key_id=None):
        """
        الـAPI الوحيد اللي بيرجّع مفتاح كامل — لمفتاح واحد بس (مفحوص الحدود).
        key_id (بصمة المفتاح اللي الواجهة شايفاه): لو مش هو اللي في الفهرس دلوقتي
        مبنرجّعش حاجة — عشان منعرضش مفتاح تاني تحت شكل مقنّع مش بتاعه.
        منسجّلش المفتاح ولا نطبعه في أي حاجة.
        """
        if pid not in providers.PROVIDERS:
            return {"ok": False, "err": "مزوّد مش معروف"}
        pool = providers.read_key_pools(core.ENV_PATH).get(pid, [])
        if isinstance(index, bool) or not isinstance(index, int) or not (0 <= index < len(pool)):
            return {"ok": False, "err": "المفتاح مش موجود"}
        if key_id is not None and providers.key_id(pool[index]) != key_id:
            return {"ok": False, "err": KEY_STALE_ERR}
        return {"ok": True, "key": pool[index]}

    def key_add(self, pid, key):
        """
        يتحقق من مفتاح جديد (verify) وبعدين يضيفه آخر المجمّعة. التحقق فشل = مبيتكتبش
        حاجة. المفتاح موجود بالفعل = مبيرحلش verify خالص.
        verify (نداء شبكة) برّه القفل عشان ميحبسش باقي عمليات المفاتيح؛ وبعده بنعيد
        فحص التكرار جوّه القفل قبل الكتابة (إضافتين متزامنتين لنفس المفتاح).
        """
        key = (key or "").strip()
        if not key:
            return {"ok": False, "err": "الصق المفتاح الأول"}
        if pid not in providers.PROVIDERS:
            return {"ok": False, "err": "مزوّد مش معروف"}
        dup = {"ok": False, "err": "المفتاح ده موجود بالفعل"}
        if key in providers.read_key_pools(core.ENV_PATH).get(pid, []):
            return dup
        ok, err = providers.verify(pid, key)
        if not ok:
            return {"ok": False, "err": err}
        with self._key_lock:
            if key in providers.read_key_pools(core.ENV_PATH).get(pid, []):
                return dup
            try:
                providers.add_provider_key(core.ENV_PATH, pid, key)
            except OSError:
                return {"ok": False, "err": KEY_WRITE_ERR}
            self._readiness_changed()
            return {"ok": True, **self.key_pool(pid)}

    def key_remove(self, pid, index, key_id=None):
        """
        يشيل مفتاح بفهرسه. key_id = بصمة المفتاح اللي الواجهة شايفاه في الفهرس ده.
        بيرفض بس لو بعد الشيل مفيش ولا ميزة تقدر تفرّغ (مفيش مزوّد تفريغ بمفتاح ولا موديل
        محلي متثبّت) — مفتاح مزوّد مفيش ميزة بتستخدمه بيتشال عادي.
        """
        if pid not in providers.PROVIDERS:
            return {"ok": False, "err": "مزوّد مش معروف"}
        if isinstance(index, bool) or not isinstance(index, int):
            return {"ok": False, "err": "المفتاح مش موجود"}
        with self._key_lock:
            pools = providers.read_key_pools(core.ENV_PATH)
            pool = pools.get(pid, [])
            if not (0 <= index < len(pool)):
                return {"ok": False, "err": "المفتاح مش موجود"}
            # لو .env اتغيّر من ورا القايمة (الفهرس بقى بيشاور على مفتاح تاني) منمسحش حاجة.
            # البصمة مش الشكل المقنّع: مفتاحين ممكن يبقوا بنفس البداية والنهاية
            if key_id is not None and providers.key_id(pool[index]) != key_id:
                return {"ok": False, "err": KEY_STALE_ERR}
            if not core.can_run(pools=dict(pools, **{pid: pool[:index] + pool[index + 1:]})):
                return {"ok": False, "err": LAST_STT_KEY_ERR}
            try:
                providers.remove_provider_key(core.ENV_PATH, pid, index)
            except OSError:
                return {"ok": False, "err": KEY_WRITE_ERR}
            self._readiness_changed()
            return {"ok": True, **self.key_pool(pid)}

    def _readiness_changed(self):
        """
        المفاتيح أو الموديل المحلي اتغيّروا: عملاء الميزات المخزّنين بيتبنوا تاني — ولو المحرك
        لسه مابدأش (اتفتحت الإعدادات من الترحيب) وبقى فيه حاجة تفرّغ، بيبدأ دلوقتي.
        """
        engine = getattr(self._c, "engine", None)
        if engine is not None:
            engine.reset_client()
        elif core.can_run():
            self._c.start_engine()

    # ── التفريغ من غير إنترنت (F9) ──
    def offline_status(self):
        """حالة الموديل المحلي + قايمة الموديلات المتاحة بأحجامها بالميجا."""
        return {
            "installed": offline.installed(),
            "residual": offline.residual(),   # ملفات باقية من تثبيت بايظ — الإزالة تفضل متاحة
            "verified": offline.cached_verification(),   # True/False بعد الفحص، None لو لسه متفحصش
            "model": core.CFG.get("offline_model", ""),
            "models": [{"id": m, "size": round(sz / 1_000_000)}
                       for m, (_u, _h, sz) in offline.MODELS.items()],
        }

    def offline_download(self, model):
        """
        بيبدأ تنزيل موديل offline في الخلفية (مينفعش يحبس نداء pywebview). التقدّم
        بيوصل للواجهة بـ onOfflineProgress {fraction}، والنتيجة بـ onOfflineDone
        {ok, model|err}. تنزيل تاني وهو شغّال بيتقفل.
        """
        with self._offline_lock:
            if self._offline_busy:
                return {"ok": False, "err": "فيه تنزيل شغّال دلوقتي"}
            if model not in offline.MODELS:
                return {"ok": False, "err": "موديل offline مش معروف"}
            self._offline_busy = True

        def run():
            try:
                offline.download(model, progress=lambda f: self._c.push("onOfflineProgress", {"fraction": f}))
                self._readiness_changed()
                self._c.push("onOfflineDone", {"ok": True, "model": model})
            except Exception as e:
                core.log_error(e, "offline/download")
                self._c.push("onOfflineDone", {"ok": False, "err": str(e)[:200]})
            finally:
                with self._offline_lock:
                    self._offline_busy = False

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def offline_remove(self):
        offline.remove()
        return {"ok": True}

    # ── متفرقات ──
    def check_update(self):
        return self._c.check_update(force=True)

    def install_update(self):
        return self._c.install_update()

    def open_url(self, url):
        if str(url).startswith(("https://", "http://")):
            webbrowser.open(url)

    def minimize(self):
        try:
            self._c.window.minimize()
        except Exception as e:
            core.log_error(e, "window/minimize")

    def close(self):
        self._c._on_closing()

    def quit(self):
        threading.Thread(target=self._c.quit, daemon=True).start()


def run(version, brand_name, brand_url):
    """بيرفع ImportError لو pywebview/pythonnet مش موجودين — emlaa.py بيرجع للواجهة القديمة."""
    import webview  # noqa: F401
    import clr      # noqa: F401
    Controller(version, brand_name, brand_url).run()
